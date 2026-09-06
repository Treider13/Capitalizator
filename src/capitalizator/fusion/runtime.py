"""Concurrent production service with per-symbol FIFO and one account writer."""

from __future__ import annotations

import copy
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from capitalizator.fusion.archive import archive_events
from capitalizator.fusion.atlas import Atlas, train
from capitalizator.fusion.concurrency import Mailbox, Supervisor
from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.exchange import Bybit, credentials
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.news import calendar as merge_news
from capitalizator.fusion.news import fetch as fetch_news
from capitalizator.fusion.news import ingest as ingest_news
from capitalizator.fusion.performance import venue_performance
from capitalizator.fusion.store import Store, encode
from capitalizator.news_macro.ingest import load_desk_calendar


class Runtime:
    def __init__(self, root: Path, config: Config, *, api_factory: Any = Bybit) -> None:
        self.root, self.config, self.api_factory = root, config, api_factory
        root.mkdir(parents=True, exist_ok=True)
        self.store = Store(root / "fusion.sqlite3")
        self.shared = Shared(self.store.meta("mode", "demo"))
        self.shared.paused = bool(self.store.meta("paused", False))
        self.shared.calendar = load_desk_calendar()
        self.shared.news_required = True
        self.supervisor = Supervisor()
        self.mailboxes = [
            Mailbox(config.queue_capacity, config.queue_quantum) for _ in range(config.workers)
        ]
        self.private_mailbox = Mailbox(config.queue_capacity, config.queue_quantum)
        self.engines = {s: Engine(s, self.store, self.shared, config) for s in config.symbols}
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
        self.recovering: set[str] = set()
        self.private_overflow_at = 0.0
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
        item = (symbol, kind, copy.deepcopy(frame), at, self.epoch if epoch is None else epoch)
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

    def _market_worker(self, index: int) -> None:
        mailbox = self.mailboxes[index]
        epochs: dict[str, int] = {}
        while not self.supervisor.stop.is_set():
            for symbol, kind, frame, at, epoch in mailbox.get():
                with self.shared.lock:
                    current_epoch = self.epoch
                if epoch != current_epoch:
                    continue
                if epochs.get(symbol) != epoch:
                    self.engines[symbol].process("gap", {"reason": "feed_generation"}, at)
                    epochs[symbol] = epoch
                if time.time() - at > self.config.max_data_age_s:
                    self.shared.halt("market_processing_lag")
                try:
                    self.engines[symbol].process(kind, frame, at)
                except (ValueError, KeyError, ArithmeticError) as exc:
                    self.engines[symbol].process("gap", {"reason": type(exc).__name__}, at)
                    self.shared.halt("invalid_market_frame")
                if kind == "book" and self.engines[symbol].market.valid:
                    with self.shared.lock:
                        self.recovering.discard(symbol)
                        if not self.recovering and self.shared.reason.startswith("recovering_feed"):
                            self.shared.halted, self.shared.reason = False, ""
            self.supervisor.beat(f"market-{index}")

    def _trainer(self) -> None:
        last_count = 0
        while not self.supervisor.stop.is_set():
            now = time.time()
            total = int(self.store.rows("SELECT count(*) AS n FROM samples")[0]["n"])
            if (
                total >= self.config.demo_samples
                and total - last_count >= self.config.retrain_samples
            ):
                rows = self.store.samples(now, self.config.training_rows)
                model = train(rows, self.config, now)
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
                or self.mode_request
                or self.supervisor.stop.is_set()
                or self.supervisor.failed.is_set()
                or order["mode"] != self.shared.mode
            ):
                return False
            market = dict(self.shared.snapshots.get(order["symbol"], {}))
        if not market.get("valid") or now >= order["expires"]:
            return False
        if not 0 <= now - market.get("book_at", 0) <= self.config.max_data_age_s:
            return False
        if not 0 <= now - market.get("ticker_at", 0) <= self.config.account_age_s:
            return False
        if self.executor is None or now - self.executor.last_reconcile > self.config.account_age_s:
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
            now = time.time()
            with self.shared.lock:
                mode, requested = self.shared.mode, self.mode_request
                reset = self.broker_reset
                self.broker_reset = False
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
                    self.executor.tick(now, allow_entries=allow and not requested)
                    self.store.put_meta(
                        "broker",
                        {"ready": True, "mode": self.executor.mode, "at": now, "error": ""},
                    )
            except Exception as exc:
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
            self.supervisor.stop.wait(0.1)

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
            if self.public_ws is not None and not self.public_ws.is_connected():
                self.shared.halt("public_socket_disconnected: resnapshot required")
            with self.shared.lock:
                reason = self.shared.reason
            recoverable = (
                "market_queue_overflow",
                "market_processing_lag",
                "public_socket_disconnected",
                "invalid_market_frame",
            )
            if (
                self.public_ws is not None
                and reason.startswith(recoverable)
                and now - last_recovery > 5
            ):
                last_recovery = now
                self.public_ws.exit()
                with self.shared.lock:
                    self.epoch += 1
                    self.recovering = set(self.config.symbols)
                    self.shared.reason = "recovering_feed"
                self._open_public()
            if reason.startswith("private_queue_overflow") and self.executor:
                # REST worker repairs unique executions/positions before clearing this halt.
                if self.executor.last_reconcile > self.private_overflow_at:
                    with self.shared.lock:
                        self.shared.halted, self.shared.reason = False, ""
            with self.supervisor.lock:
                beats = dict(self.supervisor.heartbeats)
            for name, stamp in beats.items():
                budget = (
                    max(60.0, self.config.account_age_s)
                    if name == "broker"
                    else 120.0
                    if name in {"news", "archive"}
                    else 30.0
                )
                if name != "trainer" and time.monotonic() - stamp > budget:
                    self.shared.halt("worker_stale:" + name)
            if shutil.disk_usage(self.root).free < self.config.minimum_free_disk_bytes:
                self.shared.halt("disk_space_low")
            self.supervisor.beat("maintenance")
            self.supervisor.stop.wait(1)

    def _archive(self) -> None:
        while not self.supervisor.stop.is_set():
            archive_events(self.store, self.root, time.time() - 3600, self.config.archive_batch)
            self.supervisor.beat("archive")
            self.supervisor.stop.wait(5)

    def _news(self) -> None:
        while not self.supervisor.stop.is_set():
            try:
                surprises = ingest_news(
                    self.store, fetch_news(self.config.http_timeout_s), time.time()
                )
                merged = merge_news(load_desk_calendar(), surprises)
                with self.shared.lock:
                    self.shared.calendar = merged
                    self.shared.news_at = time.time()
                self.store.event(
                    time.time(),
                    "*",
                    "news",
                    [
                        {
                            **asdict(row),
                            "event_time": row.event_time.isoformat(),
                            "known_at": row.known_at.isoformat(),
                        }
                        for row in merged
                    ],
                )
            except Exception as exc:
                self.store.put_meta(
                    "news_status", {"at": time.time(), "ok": False, "error": type(exc).__name__}
                )
            self.supervisor.beat("news")
            self.supervisor.stop.wait(60)

    def _open_public(self) -> None:
        from pybit.unified_trading import WebSocket

        ws = WebSocket(testnet=False, channel_type="linear", retries=3)
        epoch = self.epoch

        def callback(frame: dict[str, Any]) -> None:
            self.callback(frame, epoch)

        symbols = list(self.config.symbols)
        ws.orderbook_stream(50, symbols, callback)
        ws.trade_stream(symbols, callback)
        ws.ticker_stream(symbols, callback)
        ws.all_liquidation_stream(symbols, callback)
        self.public_ws = ws

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
        with self.store.transaction() as db:
            db.execute("UPDATE contracts SET state='expired' WHERE state='observing'")
        for i in range(self.config.workers):
            self.supervisor.start(f"market-{i}", lambda index=i: self._market_worker(index))
        self.supervisor.start("trainer", self._trainer)
        self.supervisor.start("broker", self._broker)
        self.supervisor.start("maintenance", self._maintenance)
        self.supervisor.start("archive", self._archive)
        if public:
            self.supervisor.start("news", self._news)
        if public:
            self._open_public()

    def control(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.shared.entry_lock:
            return self._control(action, body)

    def _control(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
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
                account = self.store.rows("SELECT body FROM account WHERE mode=?", (mode,))
                positions = json.loads(account[0]["body"])["positions"] if account else []
                if rows or any(float(p.get("size") or 0) for p in positions):
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
                    report = venue_performance(self.store, "demo")
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
                self.mode_request = mode
                self.shared.switching = True
            return {"requested": mode, "status": "pending_exchange_check"}
        if action == "pause":
            paused = body.get("paused")
            if not isinstance(paused, bool):
                raise ValueError("paused must be boolean")
            with self.shared.lock:
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

    def status(self) -> dict[str, Any]:
        with self.shared.lock:
            mode = self.shared.mode
            body = {
                "mode": mode,
                "paused": self.shared.paused,
                "halted": self.shared.halted,
                "reason": self.shared.reason,
                "mode_request": self.mode_request,
                "markets": copy.deepcopy(self.shared.snapshots),
                "model": self.shared.atlas.version if self.shared.atlas else None,
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
                "performance": venue_performance(self.store, mode),
                "orders": self.store.rows(
                    "SELECT * FROM orders WHERE mode=? ORDER BY created DESC LIMIT 30", (mode,)
                ),
                "decisions": self.store.rows("SELECT * FROM decisions ORDER BY id DESC LIMIT 40"),
                "config": asdict(self.config),
                "config_version": self.config.version,
            }
        )
        with self.supervisor.lock:
            body["worker_errors"] = dict(self.supervisor.errors)
        return body

    def close(self) -> None:
        with self.shared.lock:
            self.shared.paused = True
        # The account worker itself cancels entries in its finally clause.
        # Never call the exchange writer concurrently from this thread.
        self.supervisor.stop.set()
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
