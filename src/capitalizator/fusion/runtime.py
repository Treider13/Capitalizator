"""Concurrent production service with per-symbol FIFO and one account writer."""

from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capitalizator.fusion.archive import archive_events
from capitalizator.fusion.atlas import Atlas
from capitalizator.fusion.concurrency import Mailbox, Supervisor
from capitalizator.fusion.config import Config
from capitalizator.fusion.cross_market import entry_check
from capitalizator.fusion.daily import daily_context, daily_target
from capitalizator.fusion.diagnostics import Diagnostics
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.exchange import Bybit, credentials, news_key
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.external import bybit as public_get
from capitalizator.fusion.external import fetch_source, gamma, sources
from capitalizator.fusion.liquidation_pressure import PressureConfig
from capitalizator.fusion.news import NO_SCHEDULED_UNLOCKS
from capitalizator.fusion.news import calendar as merge_news
from capitalizator.fusion.news import fetch as fetch_news
from capitalizator.fusion.news import ingest as ingest_news
from capitalizator.fusion.performance import venue_performance
from capitalizator.fusion.risk import Instrument
from capitalizator.fusion.store import Store, encode
from capitalizator.fusion.structure import BYBIT_INTERVALS, TFS
from capitalizator.fusion.training import TrainingProcess
from capitalizator.news_macro.ingest import NewsRow, load_desk_calendar


class Runtime:
    def __init__(
        self,
        root: Path,
        config: Config,
        *,
        api_factory: Any = Bybit,
        config_path: Path | None = None,
    ) -> None:
        self.root, self.config, self.api_factory = root, config, api_factory
        self.config_path = config_path or root / "config.json"
        self.restart_requested = threading.Event()
        root.mkdir(parents=True, exist_ok=True)
        self.store = Store(root / "fusion.sqlite3")
        self.shared = Shared(self.store.meta("mode", "demo"))
        policy = self.store.meta("policy_epoch", {})
        changed_policy = policy.get("version") != config.version
        if changed_policy:
            policy = {"version": config.version, "since": time.time()}
        self.policy_since = float(policy["since"])
        self.live_qualified = self.store.meta("live_qualified_policy") == config.version
        self.shared.paused = bool(self.store.meta("paused", False)) or (
            (changed_policy or not self.live_qualified) and self.shared.mode == "live"
        )
        self.startup_pause_reason = (
            "live_policy_not_qualified"
            if (changed_policy or not self.live_qualified) and self.shared.mode == "live"
            else "persisted_pause_unknown"
            if self.shared.paused
            else "startup"
        )
        self.shared.calendar = load_desk_calendar()
        self.shared.news_required = True
        self.shared.news_coverage = {}
        self.news_sources = sources(root, config.symbols)
        self.news_source_revision = 0
        self.diagnostics = Diagnostics(root, config.version)
        self.supervisor = Supervisor(self.diagnostics.failure)
        self.watchdog_stale: set[str] = set()
        self.mailboxes = [
            Mailbox(config.queue_capacity, config.queue_quantum) for _ in range(config.workers)
        ]
        self.private_mailbox = Mailbox(config.queue_capacity, config.queue_quantum)
        pressure_error = None
        try:
            pressure_config = PressureConfig.load(root / "liquidation_pressure.json")
        except (ValueError, TypeError, OSError) as exc:
            pressure_config, pressure_error = PressureConfig(), exc
        self.engines = {
            s: Engine(s, self.store, self.shared, config, pressure_config=pressure_config)
            for s in config.symbols
        }
        if pressure_error is not None:
            for engine in self.engines.values():
                engine.pressure.fail(pressure_error)
                engine.pressure.configuration_error = engine.pressure.error
        self.routes = {s: i % config.workers for i, s in enumerate(config.symbols)}
        self.public_ws: Any = None
        self.private_ws: Any = None
        self.executor: Executor | None = None
        self.mode_request: str | None = None
        self.broker_reset = False
        self.started = time.time()
        self.rejected_frames = 0
        self._instance_fd: int | None = None
        self.epoch = 0
        self.spot_generations = {s: 0 for s in config.symbols}
        self.spot_faults: set[str] = set()
        self.recovering: set[str] = set()
        self.private_overflow_at = 0.0
        self.news_wake = threading.Event()
        self._load_model()

    def _load_model(self) -> None:
        active = self.store.meta("active_model")
        rows = self.store.rows("SELECT * FROM models WHERE version=?", (active,)) if active else []
        if rows:
            row = rows[0]
            body = json.loads(row["body"])
            if body.get("config") == self.config.version:
                self.shared.atlas = Atlas(row["version"], body, json.loads(row["report"]))

    def callback(self, frame: dict[str, Any], epoch: int | None = None) -> None:
        at = time.time()
        topic = str(frame.get("topic") or "")
        symbol = topic.rsplit(".", 1)[-1]
        kind = {
            "orderbook": "book",
            "publicTrade": "trades",
            "tickers": "ticker",
            "allLiquidation": "liquidation",
        }.get(topic.split(".")[0])
        if not kind or symbol not in self.routes:
            return
        received = {**copy.deepcopy(frame), "_received_monotonic": time.monotonic()}
        item = (symbol, kind, received, at, self.epoch if epoch is None else epoch)
        if not self.mailboxes[self.routes[symbol]].put(symbol, item):
            with self.shared.lock:
                self.rejected_frames += 1
            self.shared.halt("market_queue_overflow: restart to resnapshot")

    def private_callback(self, frame: dict[str, Any], mode: str | None = None) -> None:
        mode = mode or self.shared.mode
        if not self.private_mailbox.put("private", (copy.deepcopy(frame), time.time(), mode)):
            with self.shared.lock:
                self.private_overflow_at = time.time()
            self.shared.halt("private_queue_overflow: reconcile required")
        self.shared.broker_wake.set()

    def _market_worker(self, index: int) -> None:
        mailbox = self.mailboxes[index]
        epochs: dict[str, int] = {}
        next_pressure_clock = 0.0
        while not self.supervisor.stop.is_set():
            batch = mailbox.get()
            # Only the owning worker advances analytical time. Never inject an
            # extra item into a full market queue or run execution on timer ticks.
            if not batch and time.monotonic() >= next_pressure_clock:
                next_pressure_clock = time.monotonic() + 1.0
                for symbol, engine in self.engines.items():
                    if (
                        self.routes[symbol] == index
                        and engine.pressure.enabled
                        and engine.pressure.last_receipt is not None
                        and time.time() - engine.pressure.last_receipt
                        > engine.pressure.config.max_age_s
                    ):
                        try:
                            engine.process("pressure_clock", {}, time.time())
                        except Exception as exc:
                            engine.pressure.fail(exc)
            for symbol, kind, frame, at, epoch in batch:
                with self.shared.lock:
                    current_epoch = self.epoch
                if epoch != current_epoch:
                    continue
                if epochs.get(symbol) != epoch:
                    self.engines[symbol].process("gap", {"reason": "feed_generation"}, at)
                    epochs[symbol] = epoch
                received_mono = frame.get("_received_monotonic")
                age = (
                    time.monotonic() - received_mono
                    if received_mono is not None
                    else time.time() - at
                )
                if not 0 <= age <= self.config.max_data_age_s:
                    self.shared.halt("market_processing_lag")
                try:
                    self.engines[symbol].process(kind, frame, at)
                except (ValueError, KeyError, ArithmeticError, TypeError) as exc:
                    if kind.startswith("spot_"):
                        self.engines[symbol].process(
                            "spot_status",
                            {"generation": frame["generation"], "status": "invalid_frame"},
                            at,
                        )
                        with self.shared.lock:
                            self.spot_faults.add(symbol)
                    else:
                        self.engines[symbol].process("gap", {"reason": type(exc).__name__}, at)
                        self.shared.halt("invalid_market_frame")
                if kind == "book" and self.engines[symbol].market.valid:
                    with self.shared.lock:
                        if epoch != self.epoch:
                            continue
                        self.recovering.discard(symbol)
                        if not self.recovering and "recovering_feed" in self.shared.halts:
                            self.shared.clear_halts(
                                {"recovering_feed": self.shared.halts["recovering_feed"]}
                            )
            self.supervisor.beat(f"market-{index}")

    def _trainer(self) -> None:
        worker = TrainingProcess()
        try:
            self._train_loop(worker)
        finally:
            worker.close()

    def _train_loop(self, worker: TrainingProcess) -> None:
        last_count = 0
        while not self.supervisor.stop.is_set():
            now = time.time()
            total = int(
                self.store.rows(
                    "SELECT count(*) AS n FROM samples "
                    "WHERE json_extract(context,'$.policy_version')=?",
                    (self.config.version,),
                )[0]["n"]
            )
            if (
                total >= self.config.demo_samples
                and total - last_count >= self.config.retrain_samples
            ):
                rows = self.store.samples(now, self.config.training_rows, self.config.version)
                model = worker.fit(rows, self.config, now, self.supervisor.stop)
                last_count = total
                if model:
                    with self.store.transaction() as db:
                        db.execute(
                            "INSERT OR IGNORE INTO models VALUES(?,?,?,?)",
                            (model.version, now, encode(model.body), encode(model.report)),
                        )
                    with self.shared.lock:
                        # Live can keep a qualified champion while a candidate fails.
                        current = self.shared.atlas
                        if self.shared.mode == "demo" or model.report["passed"] or current is None:
                            self.shared.atlas = model
                            self.store.put_meta("active_model", model.version)
                    self.store.put_meta(
                        "training", {"at": now, "version": model.version, "report": model.report}
                    )
            self.supervisor.beat("trainer")
            self.supervisor.stop.wait(0.5)

    def _connect_broker(self, mode: str) -> bool:
        keys = credentials(self.root, mode)
        if keys is None:
            self.store.put_meta(
                "broker", {"ready": False, "reason": "credentials_missing", "mode": mode}
            )
            return False
        api = self.api_factory(mode, keys, self.config)
        executor = Executor(
            self.store,
            api,
            self.config,
            entry_lock=self.shared.entry_lock,
            authorize=self._authorize_send,
        )
        executor.reconcile(time.time())
        if self.mode_request and executor.positions:
            raise ValueError("target account must be flat before changing mode")
        old = self.private_ws
        if old is not None:
            old.exit()
        self.private_ws = api.private_ws(lambda frame: self.private_callback(frame, mode))
        self.executor = executor
        with self.shared.lock:
            self.shared.instruments = executor.instruments
            self.shared.mode = mode
            self.shared.broker_ready = True
        self.store.put_meta("mode", mode)
        self.store.put_meta(
            "instruments:" + mode, {s: asdict(i) for s, i in executor.instruments.items()}
        )
        self.store.put_meta("broker", {"ready": True, "mode": mode, "at": time.time()})
        return True

    def _authorize_send(self, order: dict[str, Any]) -> bool:
        now = time.time()
        with self.shared.lock:
            if (
                self.shared.paused
                or self.shared.halted
                or not self.shared.broker_ready
                or self.broker_reset
                or self.mode_request
                or self.supervisor.stop.is_set()
                or self.supervisor.failed.is_set()
                or order["mode"] != self.shared.mode
                or (self.shared.mode == "live" and not self.live_qualified)
            ):
                return False
            market = dict(self.shared.snapshots.get(order["symbol"], {}))
            spot_generation = self.spot_generations[order["symbol"]]
            spot_fault = order["symbol"] in self.spot_faults
        cross = market.get("cross_market", {})
        spec = json.loads(order["body"])
        side = 1 if spec["side"] == "Buy" else -1
        if (
            self.config.requires_spot(order["symbol"])
            and (spot_fault or cross.get("spot", {}).get("generation") != spot_generation)
        ) or entry_check(
            cross, side, now, self.config, monotonic_at=time.monotonic(), symbol=order["symbol"]
        ) != "ready":
            return False
        if not market.get("valid") or now >= order["expires"]:
            return False
        daily = daily_context(market.get("chart", {}).get("1d", {}), float(spec["price"]), now)
        daily_check = daily_target(
            daily,
            side,
            float(spec["price"]),
            float(spec["target"]),
            max(
                float(spec.get("daily_buffer", 0)),
                float(market.get("ask") or 0) - float(market.get("bid") or 0),
            ),
            now,
        )
        if not daily_check["allowed"] or daily_check["limited"]:
            return False
        if not 0 <= now - market.get("book_at", 0) <= self.config.max_data_age_s:
            return False
        if not 0 <= now - market.get("ticker_at", 0) <= self.config.account_age_s:
            return False
        if (
            self.executor is None
            or bool(getattr(self.executor, "history_error", False))
            or now - self.executor.last_reconcile > self.config.account_age_s
        ):
            return False
        contracts = self.store.rows("SELECT state FROM contracts WHERE id=?", (order["contract"],))
        return bool(
            contracts
            and contracts[0]["state"] == "confirmed"
            and self.engines[order["symbol"]].news_allows(now)
        )

    def _broker(self) -> None:
        try:
            self._broker_loop()
        finally:
            if self.executor is not None:
                try:
                    self.executor.tick(time.time(), allow_entries=False)
                except Exception as exc:
                    self.store.put_meta("shutdown_exchange_error", type(exc).__name__)

    def _broker_loop(self) -> None:
        next_connect = 0.0
        while not self.supervisor.stop.is_set():
            self.shared.broker_wake.clear()
            failed_round = False
            now = time.time()
            with self.shared.lock:
                mode, requested = self.shared.mode, self.mode_request
                reset = self.broker_reset
                self.broker_reset = False
                if reset:
                    self.shared.broker_ready = False
                allow = (
                    not self.shared.paused
                    and not self.shared.halted
                    and not self.supervisor.failed.is_set()
                )
            try:
                if reset:
                    if self.private_ws is not None:
                        self.private_ws.exit()
                        self.private_ws = None
                    self.executor = None
                    next_connect = 0
                if requested and requested != mode:
                    if self.executor:
                        self.executor.reconcile(now)
                    active = self.store.rows(
                        "SELECT id FROM orders WHERE mode=? AND state IN "
                        "('pending','sending','unknown','accepted','partial','filled','cancelling')",
                        (mode,),
                    )
                    if active or (self.executor and self.executor.positions):
                        raise ValueError("mode switch requires no positions or unresolved orders")
                    if not self._connect_broker(requested):
                        raise ValueError("target credentials missing")
                    with self.shared.lock:
                        self.mode_request = None
                        self.shared.switching = False
                elif self.executor is None and now >= next_connect:
                    self._connect_broker(mode)
                    next_connect = now + 5
                if self.executor:
                    if self.private_ws is not None and not self.private_ws.is_connected():
                        self.private_ws.exit()
                        self.private_ws = self.executor.api.private_ws(
                            lambda frame, source=self.executor.mode: self.private_callback(
                                frame, source
                            )
                        )
                        self.executor.reconcile(time.time())
                    for frame, received, source_mode in self.private_mailbox.get(timeout=0):
                        if source_mode == self.executor.mode:
                            self.executor.private(frame, received)
                        elif str(frame.get("topic", "")).startswith("execution"):
                            for row in frame.get("data", []):
                                self.store.execution(source_mode, row)
                    if self.supervisor.failed.is_set():
                        self.shared.halt("worker_failure")
                    self._protect_news(time.time())
                    self.executor.tick(now, allow_entries=allow and not requested)
                    self.store.put_meta(
                        "broker",
                        {"ready": True, "mode": self.executor.mode, "at": now, "error": ""},
                    )
            except Exception as exc:
                failed_round = True
                # Transport outage does not kill the account worker. Entries cannot
                # use an expired account snapshot; venue stops remain independent.
                reason = f"{type(exc).__name__}: {exc}"
                self.store.put_meta("broker", {"ready": False, "at": now, "error": reason})
                with self.shared.lock:
                    self.shared.broker_ready = False
                    if requested:
                        self.mode_request = None
                        self.shared.switching = False
                next_connect = now + 5
            else:
                with self.shared.lock:
                    self.shared.broker_ready = self.executor is not None
            self.supervisor.beat("broker")
            if (
                failed_round
                or self.executor is None
                or not self.private_mailbox.status()["pending"]
            ):
                self.shared.broker_wake.wait(0.1)

    def _maintenance(self) -> None:
        last_recovery = 0.0
        while not self.supervisor.stop.is_set():
            now = time.time()
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE contracts SET state='expired',updated=? "
                    "WHERE state='observing' AND json_extract(definition,'$.expires')<=?",
                    (now, now),
                )
            if (
                self.public_ws is not None
                and not self.public_ws.is_connected()
                and now - getattr(self.public_ws, "started_at", 0) > self.config.http_timeout_s
            ):
                self.shared.halt("public_socket_disconnected: resnapshot required")
            with self.shared.lock:
                incidents = dict(self.shared.halts)
            recoverable = (
                "market_queue_overflow",
                "market_processing_lag",
                "public_socket_disconnected",
                "invalid_market_frame",
            )
            if (
                self.public_ws is not None
                and any(key in recoverable for key in incidents)
                and now - last_recovery > 5
            ):
                last_recovery = now
                self.public_ws.exit()
                with self.shared.lock:
                    self.epoch += 1
                    self.recovering = set(self.config.symbols)
                    self.shared.clear_halts(
                        {key: value for key, value in incidents.items() if key in recoverable}
                    )
                    self.shared.halt("recovering_feed")
                self._open_public()
            if "private_queue_overflow" in incidents and self.executor:
                # REST worker repairs unique executions/positions before clearing this halt.
                if self.executor.last_reconcile > self.private_overflow_at:
                    with self.shared.lock:
                        self.shared.clear_halts(
                            {"private_queue_overflow": incidents["private_queue_overflow"]}
                        )
            if shutil.disk_usage(self.root).free < self.config.minimum_free_disk_bytes:
                self.shared.halt("disk_space_low")
            self.supervisor.beat("maintenance")
            self.supervisor.stop.wait(1)

    def _stale_workers(self) -> dict[str, Any]:
        now = time.monotonic()
        with self.supervisor.lock:
            beats = dict(self.supervisor.heartbeats)
        stale = {}
        for name, stamp in beats.items():
            budget = (
                max(60.0, self.config.account_age_s)
                if name == "broker"
                else self.config.macro_poll_s + 120
                if name == "macro"
                else self.config.training_timeout_s + 10
                if name == "trainer"
                else 120.0
                if name in {"news", "archive", "history", "options", "metadata"}
                else 30.0
            )
            if now - stamp > budget:
                stale[name] = {"age_s": now - stamp, "budget_s": budget}
        return stale

    def _check_workers(self) -> None:
        stale = self._stale_workers()
        new = {name: body for name, body in stale.items() if name not in self.watchdog_stale}
        if new:
            # Evidence is captured even if a stuck worker holds shared.lock or SQLite.
            self.diagnostics.stalled(new)
        recovered = self.watchdog_stale - stale.keys()
        with self.shared.lock:
            observed = {
                key: value
                for key, value in self.shared.halts.items()
                if key.startswith("worker_stale:")
                and key.removeprefix("worker_stale:") in recovered
            }
            self.shared.clear_halts(observed)
            for name in new:
                self.shared.halt("worker_stale:" + name)
        if recovered:
            self.diagnostics.record("watchdog_recovered", workers=sorted(recovered))
        self.watchdog_stale = set(stale)

    def _watchdog(self) -> None:
        next_record = 0.0
        while not self.supervisor.stop.is_set():
            self._check_workers()
            now = time.monotonic()
            if now >= next_record:
                with self.supervisor.lock:
                    ages = {name: now - at for name, at in self.supervisor.heartbeats.items()}
                self.diagnostics.record(
                    "heartbeat",
                    uptime_s=time.time() - self.started,
                    worker_age_s=ages,
                    queues=[m.status() for m in self.mailboxes],
                    private_queue=self.private_mailbox.status(),
                )
                next_record = now + 60
            self.supervisor.beat("watchdog")
            self.supervisor.stop.wait(1)

    def _archive(self) -> None:
        while not self.supervisor.stop.is_set():
            archive_events(self.store, self.root, time.time() - 3600, self.config.archive_batch)
            self.supervisor.beat("archive")
            self.supervisor.stop.wait(5)

    def _news(self) -> None:
        cache: dict[str, list[NewsRow]] = {}
        health: dict[str, Any] = {}
        previous_revision = -1
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="news-source") as pool:
            while not self.supervisor.stop.is_set():
                with self.shared.lock:
                    revision = self.news_source_revision
                    source_rows = copy.deepcopy(self.news_sources)
                if revision != previous_revision:
                    cache.clear()
                    health.clear()
                    previous_revision = revision
                at = time.time()
                try:
                    payload = fetch_news(self.config.http_timeout_s)
                    cache["bybit"] = ingest_news(self.store, payload, time.time())
                    health["bybit"] = {"ok": True, "at": time.time()}
                except Exception as exc:
                    health["bybit"] = {"ok": False, "at": time.time(), "error": type(exc).__name__}
                self._publish_news(cache, health, time.time(), revision)
                try:
                    provider_key = news_key(self.root)
                except ValueError as exc:
                    provider_key = None
                    self.store.put_meta("news_credentials_error", str(exc))
                jobs = {
                    pool.submit(
                        fetch_source, row, self.config.http_timeout_s, at, provider_key
                    ): row
                    for row in source_rows
                }
                for future in as_completed(jobs):
                    if self.supervisor.stop.is_set():
                        for job in jobs:
                            job.cancel()
                        break
                    observed = time.time()
                    row = jobs[future]
                    name = row["name"]
                    try:
                        values = future.result()
                        events: list[NewsRow] = []
                        if row["kind"] == "unlocks":
                            events = values
                        else:
                            for item in values:
                                previous = self.store.meta("news_item:" + item["id"])
                                known = previous["known_at"] if previous else observed
                                self.store.put_meta(
                                    "news_item:" + item["id"], {**item, "known_at": known}
                                )
                                if item["sentiment"] < 0 and at - item["published"] <= 3600:
                                    when = datetime.fromtimestamp(known, UTC)
                                    events.append(
                                        NewsRow(
                                            item["id"],
                                            "OTHER",
                                            when,
                                            when,
                                            tuple(item["assets"]),
                                            item["url"],
                                            "UTC",
                                            "surprise_blackout",
                                            item["title"],
                                            item["title"],
                                        )
                                    )
                        normalized = []
                        for event in events:
                            known = self.store.meta("event_known:" + event.event_id, observed)
                            self.store.put_meta("event_known:" + event.event_id, known)
                            normalized.append(
                                replace(event, known_at=datetime.fromtimestamp(known, UTC))
                            )
                        cache[name] = normalized
                        health[name] = {
                            "ok": True,
                            "at": time.time(),
                            "items": len(values),
                            "assets": row["assets"],
                            "kind": row["kind"],
                        }
                    except Exception as exc:
                        health[name] = {
                            "ok": False,
                            "at": time.time(),
                            "assets": row["assets"],
                            "error": str(exc)
                            if isinstance(exc, ValueError)
                            else type(exc).__name__,
                        }
                    self._publish_news(cache, health, time.time(), revision)
                    self.supervisor.beat("news")
                self._publish_news(cache, health, time.time(), revision)
                self.supervisor.beat("news")
                self.news_wake.wait(self.config.news_poll_s)
                self.news_wake.clear()

    def _publish_news(
        self,
        cache: dict[str, list[NewsRow]],
        health: dict[str, Any],
        now: float,
        revision: int | None = None,
    ) -> None:
        with self.shared.admission_lock:
            if revision is not None and revision != self.news_source_revision:
                return
            self._publish_news_current(cache, health, now)

    def _publish_news_current(
        self, cache: dict[str, list[NewsRow]], health: dict[str, Any], now: float
    ) -> None:
        from capitalizator.fusion.macro import coverage as macro_coverage

        with self.shared.lock:
            official = self.shared.macro_calendar
            macro_health = dict(self.shared.macro_health)
        # Live fetched schedules replace static rows of the same class. A stale
        # CSV cannot silently override a provider's changed/cancelled release.
        classes = {r.event_class for r in official}
        base = tuple(r for r in load_desk_calendar() if r.event_class not in classes) + official
        macro_missing = macro_coverage(official, macro_health, now, self.config.macro_stale_s)
        merged = merge_news(base, [r for rows in cache.values() for r in rows])
        coverage = {}
        for symbol in self.config.symbols:
            relevant = [
                r for r in self.news_sources if symbol in r["assets"] or "ALL" in r["assets"]
            ]
            missing = [
                r["name"]
                for r in relevant
                if not health.get(r["name"], {}).get("ok")
                or not 0 <= now - health[r["name"]]["at"] <= self.config.news_stale_s
            ]
            if not any(r["kind"] == "rss" for r in relevant):
                missing.append("coin_news_not_configured")
            if symbol not in NO_SCHEDULED_UNLOCKS and not any(
                r["kind"] == "unlocks" for r in relevant
            ):
                missing.append("token_unlocks_not_configured")
            missing.extend(macro_missing)
            if (
                not health.get("bybit", {}).get("ok")
                or not 0 <= now - health["bybit"].get("at", 0) <= self.config.news_stale_s
            ):
                missing.append("bybit")
            coverage[symbol] = {
                "at": now,
                "ok": not missing,
                "missing": missing,
                "unlock_coverage": any(r["kind"] == "unlocks" for r in relevant),
                "unlocks_applicable": symbol not in NO_SCHEDULED_UNLOCKS,
            }
        rows = [
            {
                **asdict(r),
                "event_time": r.event_time.isoformat(),
                "known_at": r.known_at.isoformat(),
            }
            for r in merged
        ]
        self.store.event(now, "*", "news", rows)
        self.store.event(now, "*", "news_coverage", coverage)
        with self.shared.lock:
            self.shared.calendar = merged
            self.shared.news_at = now
            self.shared.news_coverage = coverage
        self.store.put_meta(
            "news_status",
            {
                "at": now,
                "sources": {**health, "macro": macro_health},
                "coverage": coverage,
                "events": rows,
                "headlines": [
                    json.loads(r["body"])
                    for r in self.store.rows(
                        "SELECT body FROM meta WHERE key LIKE 'news_item:%' "
                        "ORDER BY json_extract(body,'$.published') DESC LIMIT 30"
                    )
                ],
            },
        )
        self.shared.broker_wake.set()

    def _macro(self) -> None:
        from capitalizator.fusion.macro import SOURCES, fetch

        cache: dict[str, list[NewsRow]] = {}
        health: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="macro-source") as pool:
            while not self.supervisor.stop.is_set():
                jobs = {
                    pool.submit(fetch, name, self.config.http_timeout_s, time.time()): name
                    for name in SOURCES
                }
                for future in as_completed(jobs):
                    name, now = jobs[future], time.time()
                    try:
                        values = future.result()
                        normalized = []
                        for value in values:
                            known = self.store.meta("event_known:" + value.event_id, now)
                            self.store.put_meta("event_known:" + value.event_id, known)
                            normalized.append(
                                replace(value, known_at=datetime.fromtimestamp(known, UTC))
                            )
                        cache[name] = normalized
                        health[name] = {
                            "ok": True,
                            "at": now,
                            "events": len(normalized),
                            "source": normalized[0].source if normalized else SOURCES[name],
                            "sources": sorted({r.source for r in normalized}),
                            "fallback": any(r.source != SOURCES[name] for r in normalized),
                        }
                    except Exception as exc:
                        health[name] = {
                            "ok": False,
                            "at": now,
                            "error": type(exc).__name__,
                            "source": SOURCES[name],
                            "http_status": getattr(exc, "code", None),
                        }
                combined = tuple(r for rows in cache.values() for r in rows)
                self.store.event(
                    time.time(),
                    "*",
                    "macro",
                    {
                        "health": health,
                        "events": [
                            {
                                **asdict(r),
                                "event_time": r.event_time.isoformat(),
                                "known_at": r.known_at.isoformat(),
                            }
                            for r in combined
                        ],
                    },
                )
                with self.shared.lock:
                    self.shared.macro_calendar = combined
                    self.shared.macro_health = copy.deepcopy(health)
                self.news_wake.set()
                self.supervisor.beat("macro")
                self.supervisor.stop.wait(self.config.macro_poll_s)

    def _protect_news(self, at: float) -> None:
        """Broker-owned reaction, shared with recorded-event replay."""
        from capitalizator.fusion.news import protect

        if self.executor is None:
            return
        with self.shared.lock:
            calendar = self.shared.calendar
        protect(
            self.store,
            calendar,
            self.executor.mode,
            self.config.symbols,
            at,
            self.config.news_post_minutes,
        )

    def _history(self) -> None:
        # Independent reads run concurrently; only the symbol owner mutates bars.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="history-source") as pool:
            while not self.supervisor.stop.is_set():
                epoch = self.epoch
                jobs = {
                    pool.submit(
                        public_get,
                        "market/kline",
                        {
                            "category": "linear",
                            "symbol": symbol,
                            "interval": BYBIT_INTERVALS[tf],
                            "limit": 256,
                        },
                        self.config.http_timeout_s,
                    ): (symbol, tf)
                    for symbol in self.config.symbols
                    for tf in TFS
                }
                for future in as_completed(jobs):
                    if self.supervisor.stop.is_set():
                        for job in jobs:
                            job.cancel()
                        return
                    symbol, tf = jobs[future]
                    try:
                        result = future.result()
                        item = (
                            symbol,
                            "history",
                            {
                                "tf": tf,
                                "rows": result["list"],
                                "known_at": result["_known_at"],
                                "_received_monotonic": time.monotonic(),
                            },
                            time.time(),
                            epoch,
                        )
                        if not self.mailboxes[self.routes[symbol]].put(symbol, item):
                            self.shared.halt("market_queue_overflow: history")
                    except Exception as exc:
                        self.store.put_meta(
                            "history:" + symbol + ":" + tf,
                            {"at": time.time(), "error": type(exc).__name__},
                        )
                    self.supervisor.beat("history")
                self.supervisor.stop.wait(self.config.context_poll_s)

    def _metadata(self) -> None:
        # Tick sizes are public facts. Training must not depend on private API keys
        # or assume that every asset (especially low-price alts) has tick=0.1.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="instrument-source") as pool:
            while not self.supervisor.stop.is_set():
                jobs = {
                    pool.submit(
                        public_get,
                        "market/instruments-info",
                        {"category": "linear", "symbol": symbol},
                        self.config.http_timeout_s,
                    ): symbol
                    for symbol in self.config.symbols
                }
                for future in as_completed(jobs):
                    if self.supervisor.stop.is_set():
                        for job in jobs:
                            job.cancel()
                        return
                    symbol = jobs[future]
                    try:
                        rows = future.result()["list"]
                        if not rows or rows[0].get("status") != "Trading":
                            raise ValueError("instrument_not_trading")
                        instrument = Instrument.parse(
                            rows[0], (self.config.demo_maker_fee, self.config.demo_taker_fee)
                        )
                        with self.shared.lock:
                            self.shared.public_instruments[symbol] = instrument
                        self.store.put_meta(
                            "public_instrument:" + symbol,
                            {
                                "at": time.time(),
                                "ok": True,
                                "tick": instrument.tick,
                                "fees": "configured_demo_estimate",
                            },
                        )
                    except Exception as exc:
                        self.store.put_meta(
                            "public_instrument:" + symbol,
                            {
                                "at": time.time(),
                                "ok": False,
                                "error": type(exc).__name__,
                            },
                        )
                    self.supervisor.beat("metadata")
                self.supervisor.stop.wait(self.config.context_poll_s)

    def _options(self) -> None:
        while not self.supervisor.stop.is_set():
            for symbol in self.config.symbols:
                if self.supervisor.stop.is_set():
                    return
                try:
                    result = public_get(
                        "market/tickers",
                        {"category": "option", "baseCoin": symbol[:-4]},
                        self.config.http_timeout_s,
                    )
                    value = gamma(result["list"], time.time())
                    with self.shared.lock:
                        prior = self.shared.external.get(symbol, {})
                    if value.get("available") and prior.get("available"):
                        previous = float(prior.get("gross_gamma_1pct") or 0)
                        value["gross_change"] = (
                            (value["gross_gamma_1pct"] / previous - 1) if previous else None
                        )
                        value["iv_change"] = value["weighted_iv"] - prior["weighted_iv"]
                except Exception as exc:
                    value = {"at": time.time(), "available": False, "error": type(exc).__name__}
                self.store.event(time.time(), symbol, "options", value)
                with self.shared.lock:
                    self.shared.external[symbol] = value
                self.supervisor.beat("options")
            self.supervisor.stop.wait(self.config.context_poll_s)

    def _open_public(self) -> None:
        from capitalizator.fusion.public import RawPublic

        epoch = self.epoch
        self.public_ws = RawPublic(self.config.symbols, lambda frame: self.callback(frame, epoch))

    def _spot_event(
        self, symbol: str, kind: str, frame: dict[str, Any], generation: int, epoch: int
    ) -> None:
        with self.shared.lock:
            if generation != self.spot_generations[symbol] or epoch != self.epoch:
                return
        item = (
            symbol,
            kind,
            {
                **copy.deepcopy(frame),
                "generation": generation,
                "_received_monotonic": time.monotonic(),
            },
            time.time(),
            epoch,
        )
        if not self.mailboxes[self.routes[symbol]].put(symbol, item):
            if self.supervisor.stop.is_set():
                return
            with self.shared.lock:
                self.spot_faults.add(symbol)
                self.rejected_frames += 1
            self.shared.halt("market_queue_overflow: spot resnapshot required")

    def _spot_status(self, symbol: str, status: str) -> tuple[int, int]:
        # Revoke the old generation before waiting on any network or mailbox.
        with self.shared.lock:
            self.spot_generations[symbol] += 1
            generation, epoch = self.spot_generations[symbol], self.epoch
        self._spot_event(symbol, "spot_status", {"status": status}, generation, epoch)
        return generation, epoch

    def _spot_worker(self, symbol: str) -> None:
        """One independent public connection/discovery task per configured symbol.

        Exact same-base USDT spot only. XAU is never silently mapped to PAXG/XAUT.
        Socket callbacks enqueue; all L2 mutation stays with the symbol actor.
        """
        from capitalizator.fusion.public import RawPublic

        if not self.config.requires_spot(symbol):
            return

        wire: Any = None
        generation, epoch = self._spot_status(symbol, "discovery_pending")
        next_discovery = 0.0
        retry_delay = 1.0
        name = "spot-" + symbol
        try:
            while not self.supervisor.stop.is_set():
                now = time.monotonic()
                with self.shared.lock:
                    fault = symbol in self.spot_faults
                    self.spot_faults.discard(symbol)
                    changed = epoch != self.epoch
                lost = wire is not None and (
                    wire.closed.is_set()
                    or (not wire.is_connected() and now - wire.last_message > 10)
                    or now - wire.last_data_message > max(10, self.config.max_data_age_s * 2)
                )
                if fault or changed or lost:
                    generation, epoch = self._spot_status(symbol, "reconnecting")
                    if wire is not None:
                        wire.exit()
                        wire = None
                    next_discovery = now + retry_delay
                    retry_delay = min(30.0, retry_delay * 2)
                elif (
                    wire is not None
                    and wire.is_connected()
                    and now - wire.started_at_monotonic > 30
                ):
                    retry_delay = 1.0
                if now >= next_discovery:
                    try:
                        result = public_get(
                            "market/instruments-info",
                            {"category": "spot", "symbol": symbol},
                            self.config.http_timeout_s,
                        )
                        available = any(
                            row.get("symbol") == symbol
                            and row.get("baseCoin") == symbol[:-4]
                            and row.get("quoteCoin") == "USDT"
                            and row.get("status") == "Trading"
                            for row in result["list"]
                        )
                        if not available:
                            generation, epoch = self._spot_status(symbol, "instrument_unavailable")
                            if wire is not None:
                                wire.exit()
                                wire = None
                        elif wire is None:
                            generation, epoch = self._spot_status(symbol, "awaiting_snapshot")

                            def on_spot(
                                frame: dict[str, Any], g: int = generation, e: int = epoch
                            ) -> None:
                                self._spot_event(symbol, "spot_book", frame, g, e)

                            wire = RawPublic(
                                (symbol,),
                                on_spot,
                                category="spot",
                            )
                    except Exception as exc:
                        generation, epoch = self._spot_status(
                            symbol, "discovery_error:" + type(exc).__name__
                        )
                        if wire is not None:
                            wire.exit()
                            wire = None
                    next_discovery = time.monotonic() + self.config.context_poll_s
                self.supervisor.beat(name)
                self.supervisor.stop.wait(0.25)
        finally:
            self._spot_status(symbol, "stopped")
            if wire is not None:
                wire.exit()

    def start(self, *, public: bool = True) -> None:
        import fcntl

        fd = os.open(self.root / "runtime.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RuntimeError(
                "another fusion runtime already owns this account directory"
            ) from None
        self._instance_fd = fd
        self.diagnostics.record(
            "startup",
            mode=self.shared.mode,
            paused=self.shared.paused,
            previous_failure_run=(self.diagnostics.last_failure or {}).get("run_id"),
        )
        # A second instance may inspect storage, but cannot alter the active
        # policy/paused state before it owns the process lock.
        self.store.put_meta(
            "policy_epoch",
            {
                "version": self.config.version,
                "since": self.policy_since,
            },
        )
        self.store.put_meta("paused", self.shared.paused)
        pause_state = self.store.meta("pause_state")
        if (
            not isinstance(pause_state, dict)
            or pause_state.get("paused") != self.shared.paused
            or self.startup_pause_reason == "live_policy_not_qualified"
        ):
            self.store.put_meta(
                "pause_state",
                {
                    "paused": self.shared.paused,
                    "at": time.time(),
                    "reason": self.startup_pause_reason,
                },
            )
        with self.store.transaction() as db:
            db.execute("UPDATE contracts SET state='expired' WHERE state='observing'")
        for i in range(self.config.workers):
            self.supervisor.start(f"market-{i}", lambda index=i: self._market_worker(index))
        self.supervisor.start("trainer", self._trainer)
        self.supervisor.start("broker", self._broker)
        self.supervisor.start("maintenance", self._maintenance)
        self.supervisor.start("watchdog", self._watchdog)
        self.supervisor.start("archive", self._archive)
        if public:
            self.supervisor.start("metadata", self._metadata)
            self.supervisor.start("macro", self._macro)
            self.supervisor.start("news", self._news)
            self.supervisor.start("history", self._history)
            self.supervisor.start("options", self._options)
        if public:
            self._open_public()
            for symbol in self.config.symbols:
                if self.config.requires_spot(symbol):
                    self.supervisor.start("spot-" + symbol, lambda s=symbol: self._spot_worker(s))

    def control(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        qualification = None
        if action == "mode" and body.get("mode") == "live":
            qualification = venue_performance(
                self.store, "demo", self.policy_since, self.config.version
            )
        with self.shared.entry_lock:
            with self.shared.admission_lock:
                result = self._control(action, body, qualification)
                if action in {"pause", "flatten", "settings"}:
                    pause_state = {
                        "paused": self.shared.paused or self.restart_requested.is_set(),
                        "at": time.time(),
                        "reason": "operator_" + action,
                    }
                    self.store.put_meta("pause_state", pause_state)
                    self.diagnostics.record("pause_change", **pause_state)
        self.shared.broker_wake.set()
        return result

    def _control(
        self, action: str, body: dict[str, Any], qualification: Any = None
    ) -> dict[str, Any]:
        if self.restart_requested.is_set():
            raise ValueError("configuration restart in progress")
        if action == "news_sources":
            from capitalizator.fusion.external import validate_sources

            rows = validate_sources(body.get("sources"), self.config.symbols)
            with self.shared.lock:
                if not self.shared.paused:
                    raise ValueError("pause entries before changing news sources")
            path = self.root / "news_sources.json"
            temp = path.with_name("." + uuid.uuid4().hex)
            try:
                with temp.open("x", encoding="utf-8") as stream:
                    json.dump(rows, stream, indent=2, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            with self.shared.lock:
                self.shared.news_coverage = {}
                self.news_sources = copy.deepcopy(rows)
                self.news_source_revision += 1
            self.news_wake.set()
            return {"status": "sources_saved", "coverage": "awaiting_new_fetch"}
        if action == "settings":
            allowed = {"max_positions", "trade_margin_fraction", "max_stop_fraction", "leverage"}
            if not body or set(body) - allowed:
                raise ValueError("unsupported trading setting")
            updated = replace(self.config, **body)
            if updated.max_positions > len(updated.symbols):
                raise ValueError("max_positions exceeds configured symbol count")
            with self.shared.lock:
                if not self.shared.paused or self.mode_request:
                    raise ValueError(
                        "pause entries and finish mode switch before changing settings"
                    )
                settings_mode = self.shared.mode
            active = self.store.rows(
                "SELECT id FROM orders WHERE mode=? AND state IN "
                "('pending','sending','unknown','accepted','partial','filled','cancelling')",
                (settings_mode,),
            )
            accounts = self.store.rows("SELECT at,body FROM account WHERE mode=?", (settings_mode,))
            if active:
                raise ValueError("resolve orders and close positions before changing settings")
            if accounts or credentials(self.root, settings_mode) is not None:
                if (
                    not accounts
                    or not 0 <= time.time() - accounts[0]["at"] <= self.config.account_age_s
                ):
                    raise ValueError("fresh account reconciliation required")
                account = json.loads(accounts[0]["body"])
                if account["orders"] or any(
                    float(p.get("size") or 0) for p in account["positions"]
                ):
                    raise ValueError("account must have no positions or venue orders")
            if updated == self.config:
                return {"status": "unchanged", "config": asdict(updated)}
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.config_path.with_name("." + uuid.uuid4().hex)
            try:
                with temp.open("x", encoding="utf-8") as stream:
                    json.dump(asdict(updated), stream, indent=2, allow_nan=False)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, self.config_path)
            finally:
                temp.unlink(missing_ok=True)
            self.store.put_meta("paused", True)
            self.restart_requested.set()
            return {"status": "restart_requested", "paused": True, "config": asdict(updated)}
        if action == "news_credentials":
            key = body.get("key")
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Tokenomist key required")
            directory = self.root / "secrets"
            directory.mkdir(mode=0o700, exist_ok=True)
            temp = directory / ("." + uuid.uuid4().hex)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump({"key": key.strip()}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, directory / "tokenomist.json")
            finally:
                temp.unlink(missing_ok=True)
            return {"saved": "tokenomist", "status": "applied_on_next_news_fetch"}
        if action == "credentials":
            mode = body.get("mode")
            key, secret = body.get("key"), body.get("secret")
            if mode not in {"demo", "live"}:
                raise ValueError("only demo/live credentials accepted")
            if not isinstance(key, str) or not isinstance(secret, str) or not key or not secret:
                raise ValueError("key and secret required")
            with self.shared.lock:
                if not self.shared.paused:
                    raise ValueError("pause entries before changing credentials")
                rows = self.store.rows(
                    "SELECT id FROM orders WHERE mode=? AND state IN "
                    "('pending','sending','unknown','accepted','partial','filled','cancelling')",
                    (mode,),
                )
                account = self.store.rows("SELECT at,body FROM account WHERE mode=?", (mode,))
                if account or credentials(self.root, mode) is not None:
                    if (
                        not account
                        or not 0 <= time.time() - account[0]["at"] <= self.config.account_age_s
                    ):
                        raise ValueError("fresh account reconciliation required")
                positions = json.loads(account[0]["body"])["positions"] if account else []
                venue_orders = json.loads(account[0]["body"])["orders"] if account else []
                pending = self.store.rows(
                    "SELECT id FROM commands WHERE mode=? "
                    "AND state IN ('pending','failed') LIMIT 1",
                    (mode,),
                )
                if (
                    rows
                    or venue_orders
                    or pending
                    or any(float(p.get("size") or 0) for p in positions)
                ):
                    raise ValueError("account must be flat before changing credentials")
                directory = self.root / "secrets"
                directory.mkdir(mode=0o700, exist_ok=True)
                temp = directory / ("." + uuid.uuid4().hex)
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "w") as stream:
                        json.dump({"mode": mode, "key": key, "secret": secret}, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, directory / f"{mode}.json")
                finally:
                    temp.unlink(missing_ok=True)
                self.broker_reset = mode == self.shared.mode
                if self.broker_reset:
                    self.shared.broker_ready = False
            return {"saved": mode}
        if action == "mode":
            mode = body.get("mode")
            if mode not in {"demo", "live"}:
                raise ValueError("only demo and live modes exist")
            with self.shared.lock:
                if mode == self.shared.mode and self.mode_request is None:
                    return {"mode": mode, "status": "unchanged"}
                model = self.shared.atlas
                if mode == "live" and (model is None or not model.report.get("passed")):
                    raise ValueError("live requires a model with a passed chronological test")
                if mode == "live":
                    report = qualification
                    if report is None:
                        raise ValueError("demo qualification report missing")
                    if (
                        report["closed_episodes"] < 32
                        or report["realized_net"] <= 0
                        or report["incomplete_inventory"]
                        or (report["lower_episode_net"] or 0) <= 0
                    ):
                        raise ValueError(
                            "live requires complete demo inventory and 32 closed episodes "
                            "with positive block-bootstrap lower net estimate"
                        )
                if mode == "live":
                    self.live_qualified = True
                    self.store.put_meta("live_qualified_policy", self.config.version)
                self.mode_request = mode
                self.shared.switching = True
            return {"requested": mode, "status": "pending_exchange_check"}
        if action == "pause":
            paused = body.get("paused")
            if not isinstance(paused, bool):
                raise ValueError("paused must be boolean")
            with self.shared.lock:
                if not paused and self.shared.mode == "live" and not self.live_qualified:
                    raise ValueError("changed policy requires new Demo qualification before Live")
                self.shared.paused = paused
            self.store.put_meta("paused", paused)
            return {"paused": paused}
        if action == "flatten":
            with self.shared.lock:
                self.shared.paused = True
                mode = self.shared.mode
            self.store.put_meta("paused", True)
            for symbol in self.config.symbols:
                self.store.command(
                    f"operator-{symbol}-{time.time_ns()}",
                    mode,
                    symbol,
                    "flatten",
                    time.time(),
                    {"reason": "operator"},
                )
            return {"status": "close_requested", "paused": True}
        raise ValueError("unknown control action")

    def chart(self, symbol: str, tf: str, revision: float = -1) -> dict[str, Any]:
        if symbol not in self.config.symbols or tf not in TFS:
            raise ValueError("unsupported chart symbol/timeframe")
        with self.shared.lock:
            market = self.shared.snapshots.get(symbol, {})
            mode = self.shared.mode
            options = self.shared.external.get(symbol, {})
        series = market.get("chart", {}).get(tf, {})
        closed_at = market.get("chart_revision", 0)
        contracts = self.store.rows(
            "SELECT * FROM contracts WHERE symbol=? ORDER BY at DESC LIMIT 30", (symbol,)
        )
        fills = self.store.rows(
            "SELECT id,at,body FROM executions WHERE mode=? AND symbol=? "
            "ORDER BY at DESC LIMIT 100",
            (mode, symbol),
        )
        orders = self.store.rows(
            "SELECT id,state,body FROM orders WHERE mode=? AND symbol=? "
            "ORDER BY created DESC LIMIT 30",
            (mode, symbol),
        )
        accounts = self.store.rows("SELECT at,body FROM account WHERE mode=?", (mode,))
        data_errors: list[dict[str, Any]] = []

        def parsed(row: dict[str, Any], key: str, source: str) -> dict[str, Any] | None:
            try:
                value = json.loads(row[key])
                if not isinstance(value, dict):
                    raise ValueError("object required")
                return value
            except (ValueError, TypeError, KeyError) as exc:
                data_errors.append({"source": source, "id": row.get("id"), "error": str(exc)})
                return None

        account = parsed(accounts[0], "body", "account") if accounts else None
        positions = []
        if account is not None:
            try:
                positions = [
                    p
                    for p in account["positions"]
                    if p["symbol"] == symbol and float(p.get("size") or 0)
                ]
            except (ValueError, TypeError, KeyError) as exc:
                data_errors.append({"source": "positions", "error": str(exc)})
        contract_rows = [
            {**c, "definition": value}
            for c in contracts
            if (value := parsed(c, "definition", "contracts")) is not None
        ]
        fill_rows = [
            {**value, "at": f["at"]}
            for f in fills
            if (value := parsed(f, "body", "executions")) is not None
        ]
        order_rows = [
            {**value, "state": o["state"]}
            for o in orders
            if (value := parsed(o, "body", "orders")) is not None
        ]
        now, monotonic_at = time.time(), time.monotonic()
        body = {
            "at": now,
            "monotonic_at": monotonic_at,
            "data_errors": data_errors,
            "symbol": symbol,
            "mode": mode,
            "tf": tf,
            "revision": closed_at,
            "quote": {k: market.get(k) for k in ("bid", "ask", "book_at", "valid")},
            "book_levels": market.get("book_levels", {}),
            "spot_levels": market.get("spot_levels", {}),
            "cross_market": market.get("cross_market", {}),
            "liquidation_pressure": market.get("liquidation_pressure", {}),
            "book_entry_checks": {
                "Buy": entry_check(
                    market.get("cross_market", {}),
                    1,
                    now,
                    self.config,
                    monotonic_at=monotonic_at,
                    symbol=symbol,
                ),
                "Sell": entry_check(
                    market.get("cross_market", {}),
                    -1,
                    now,
                    self.config,
                    monotonic_at=monotonic_at,
                    symbol=symbol,
                ),
            },
            "max_data_age_s": self.config.max_data_age_s,
            "forming": market.get("forming", {}).get(tf),
            "block": market.get("block"),
            "analytics": market.get("analytics", []),
            "structure": {k: v for k, v in series.items() if k != "candles"},
            "daily": daily_context(
                market.get("chart", {}).get("1d", {}), float(market.get("bid") or 0), now
            ),
            "options": options,
            "contracts": contract_rows,
            "fills": fill_rows,
            "orders": order_rows,
            "positions": positions,
            "account_at": accounts[0]["at"] if accounts else None,
        }
        if revision != closed_at:
            body["candles"] = series.get("candles", [])
        return body

    def maintenance_commands(self) -> dict[str, Any]:
        """Show existing offline tools with actual paths; never run them via HTTP."""
        root = self.root.resolve()
        suffix = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.started))
        config = (
            " --config " + shlex.quote(str(self.config_path.resolve()))
            if self.config_path.exists()
            else ""
        )
        return {
            "shell": "POSIX",
            "commands": [
                "# Linux / macOS (POSIX). Use a NEW output directory for each run.",
                "python -m capitalizator.fusion.replay --userdir "
                + shlex.quote(str(root))
                + " --output "
                + shlex.quote(str(root.parent / (root.name + "-replay-" + suffix)))
                + config,
                "python -m capitalizator.fusion.backup --userdir "
                + shlex.quote(str(root))
                + " --dest "
                + shlex.quote(str(root.parent / (root.name + "-backup-" + suffix))),
            ],
        }

    def console_performance(self, mode: str) -> dict[str, Any]:
        try:
            return venue_performance(self.store, mode)
        except (ValueError, TypeError, KeyError) as exc:
            return {"error": str(exc), "realized_net": None, "closed_episodes": None}

    def status(self) -> dict[str, Any]:
        pause_state = self.store.meta("pause_state")
        with self.shared.lock:
            mode = self.shared.mode
            body = {
                "mode": mode,
                "paused": self.shared.paused,
                "pause_state": pause_state,
                "last_failure": self.diagnostics.last_failure,
                "run_id": self.diagnostics.run_id,
                "halted": self.shared.halted,
                "reason": self.shared.reason,
                "halt_reasons": [value[1] for value in self.shared.halts.values()],
                "mode_request": self.mode_request,
                "markets": {
                    symbol: {
                        k: v
                        for k, v in snapshot.items()
                        if k not in {"chart", "forming", "analytics", "book_levels", "spot_levels"}
                    }
                    for symbol, snapshot in self.shared.snapshots.items()
                },
                "options": dict(self.shared.external),
                "model": self.shared.atlas.version if self.shared.atlas else None,
                "active_model_report": (
                    copy.deepcopy(self.shared.atlas.report) if self.shared.atlas else None
                ),
            }
        accounts = self.store.rows("SELECT * FROM account WHERE mode=?", (mode,))
        body.update(
            {
                "at": time.time(),
                "uptime_s": time.time() - self.started,
                "account": accounts[0] if accounts else None,
                "broker": self.store.meta("broker"),
                "training": self.store.meta("training"),
                "news": self.store.meta("news_status"),
                "queues": [m.status() for m in self.mailboxes],
                "private_queue": self.private_mailbox.status(),
                "performance": self.console_performance(mode),
                "orders": self.store.rows(
                    "SELECT * FROM orders WHERE mode=? ORDER BY created DESC LIMIT 30", (mode,)
                ),
                "decisions": self.store.rows("SELECT * FROM decisions ORDER BY id DESC LIMIT 40"),
                "config": asdict(self.config),
                "news_sources": copy.deepcopy(self.news_sources),
                "config_version": self.config.version,
                "policy_since": self.policy_since,
                "maintenance": self.maintenance_commands(),
                "restart_requested": self.restart_requested.is_set(),
            }
        )
        with self.supervisor.lock:
            body["worker_errors"] = dict(self.supervisor.errors)
        body["at"], body["monotonic_at"] = time.time(), time.monotonic()
        return body

    def health(self) -> dict[str, Any]:
        """Liveness is independent of a legitimate trading pause or rejected model."""
        with self.supervisor.lock:
            errors = dict(self.supervisor.errors)
            dead = [t.name for t in self.supervisor.threads if not t.is_alive()]
        stale = self._stale_workers()
        return {
            "healthy": not (errors or dead or stale or self.supervisor.stop.is_set()),
            "worker_errors": errors,
            "stopped_workers": dead,
            "stale_workers": stale,
            "uptime_s": time.time() - self.started,
            "run_id": self.diagnostics.run_id,
        }

    def close(self) -> None:
        with self.shared.lock:
            self.shared.paused = True
        # The account worker itself cancels entries in its finally clause.
        # Never call the exchange writer concurrently from this thread.
        self.supervisor.stop.set()
        self.shared.broker_wake.set()
        self.news_wake.set()
        for mailbox in (*self.mailboxes, self.private_mailbox):
            mailbox.close()
        remaining = self.supervisor.join()
        if remaining:
            raise RuntimeError("workers did not terminate: " + ",".join(remaining))
        for ws in (self.public_ws, self.private_ws):
            if ws is not None:
                ws.exit()
        self.store.close()
        if self._instance_fd is not None:
            os.close(self._instance_fd)
            self._instance_fd = None
