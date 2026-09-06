"""Market actor: context -> Atlas -> reaction contract -> risk outbox.

No network calls and no model fitting on this path. Training labels mature even
when the strategy abstains. Modes do not change market observations.
"""

from __future__ import annotations

import json
import math
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from capitalizator.fusion.atlas import Atlas
from capitalizator.fusion.concurrency import FairLock
from capitalizator.fusion.config import Config
from capitalizator.fusion.contracts import Contract, baseline, propose
from capitalizator.fusion.cross_market import entry_check
from capitalizator.fusion.daily import daily_context, daily_target
from capitalizator.fusion.market import Block, Market
from capitalizator.fusion.risk import Instrument, reserve
from capitalizator.fusion.store import Store, encode
from capitalizator.news_macro.ingest import NewsRow


class Shared:
    def __init__(self, mode: str = "demo") -> None:
        if mode not in {"demo", "live"}:
            raise ValueError("mode must be demo/live")
        self.lock = threading.RLock()
        self.entry_lock = FairLock()
        self.admission_lock = FairLock()
        self.broker_wake = threading.Event()
        self.external: dict[str, dict[str, Any]] = {}
        self.mode = mode
        self.paused = False
        self.halts: dict[str, tuple[int, str]] = {}
        self.halt_revision = 0
        self.atlas: Atlas | None = None
        self.instruments: dict[str, Instrument] = {}
        self.public_instruments: dict[str, Instrument] = {}
        self.snapshots: dict[str, Any] = {}
        self.calendar: tuple[NewsRow, ...] = ()
        self.macro_calendar: tuple[NewsRow, ...] = ()
        self.macro_health: dict[str, Any] = {}
        self.broker_ready = False
        self.switching = False
        self.news_required = False
        self.news_at = 0.0
        self.news_coverage: dict[str, Any] | None = None

    def halt(self, reason: str) -> None:
        with self.lock:
            self.halt_revision += 1
            key = reason if reason.startswith("worker_stale:") else reason.split(":", 1)[0]
            self.halts[key] = (self.halt_revision, reason)

    @property
    def halted(self) -> bool:
        with self.lock:
            return bool(self.halts)

    @property
    def reason(self) -> str:
        with self.lock:
            return "; ".join(value[1] for value in self.halts.values())

    def clear_halts(self, observed: dict[str, tuple[int, str]]) -> None:
        """Clear only the exact incidents repaired, never a newer or unrelated fault."""
        with self.lock:
            for key, value in observed.items():
                if self.halts.get(key) == value:
                    del self.halts[key]


class Engine:
    def __init__(
        self, symbol: str, store: Store, shared: Shared, config: Config, *, variant: str = "D"
    ) -> None:
        if variant not in {"A", "B", "C", "D"}:
            raise ValueError("unknown ablation variant")
        self.variant = variant
        self.symbol, self.store, self.shared, self.config = symbol, store, shared, config
        self.market = Market(symbol, config)
        self.unlabeled: deque[Block] = deque()
        self.origin_costs: dict[int, float] = {}
        self.future: deque[Block] = deque(maxlen=config.horizon_blocks + 2)
        self.contract: Contract | None = None
        self.contract_state = "none"

    def process(self, kind: str, frame: dict[str, Any], at: float) -> None:
        if kind in {"book", "spot_book"} and not isinstance(frame.get("data"), dict):
            raise ValueError("book_payload_must_be_an_object")
        with self.shared.lock:
            instrument = self.shared.instruments.get(
                self.symbol
            ) or self.shared.public_instruments.get(self.symbol)
        if instrument:
            if self.market.tick != instrument.tick:
                self.market.tick = instrument.tick
                self.process("gap", {"reason": "instrument_tick_changed"}, at)
            self.market.tick = instrument.tick
        if (
            kind == "book"
            and self.market.book_u
            and (frame.get("type") == "snapshot" or frame.get("data", {}).get("u") == 1)
        ):
            self.process("gap", {"reason": "venue_book_reset"}, at)
        self.store.event(
            at,
            self.symbol,
            kind,
            {k: v for k, v in frame.items() if k != "_received_monotonic"},
        )
        if kind == "gap":
            self.unlabeled.clear()
            self.origin_costs.clear()
            self.future.clear()
            if self.contract:
                self.transition("expired", at, "data_gap")
        for block in self.market.ingest(kind, frame, at):
            self.on_block(block)
        snapshot = self.market.snapshot()
        with self.shared.lock:
            self.shared.snapshots[self.symbol] = snapshot

    def transition(self, state: str, at: float, reason: str) -> None:
        assert self.contract is not None
        with self.store.transaction() as db:
            db.execute(
                "UPDATE contracts SET state=?,updated=? WHERE id=?", (state, at, self.contract.id)
            )
        self.contract_state = state
        self.store.decision(
            at, self.symbol, "contract_" + state, {"contract": self.contract.id, "reason": reason}
        )

    def news_allows(self, at: float) -> bool:
        with self.shared.lock:
            calendar = self.shared.calendar
            if self.shared.news_required and self.shared.news_coverage is not None:
                source = self.shared.news_coverage.get(self.symbol, {})
                if (
                    not source.get("ok")
                    or not 0 <= at - source.get("at", 0) <= self.config.news_stale_s
                ):
                    return False
            if (
                self.shared.news_required
                and not 0 <= at - self.shared.news_at <= self.config.news_stale_s
            ):
                return False
        now = datetime.fromtimestamp(at, UTC)
        for row in calendar:
            if row.size_rule == "linear_supply_context":
                continue
            if row.known_at > now:
                continue
            if row.assets and self.symbol not in row.assets and "ALL" not in row.assets:
                if row.event_class not in {"CPI", "FOMC", "NFP", "PCE"}:
                    continue
            if (
                row.event_time - timedelta(minutes=self.config.news_pre_minutes)
                <= now
                <= row.event_time + timedelta(minutes=self.config.news_post_minutes)
            ):
                return False
        return True

    def _learn(self, block: Block, costs: float) -> None:
        self.future.append(block)
        self.unlabeled.append(block)
        self.origin_costs[block.id] = costs
        while self.unlabeled and block.id - self.unlabeled[0].id >= self.config.horizon_blocks:
            origin = self.unlabeled.popleft()
            origin_cost = self.origin_costs.pop(origin.id)
            after = [b for b in self.future if origin.id < b.id <= block.id]
            if block.at <= origin.at or len(after) != self.config.horizon_blocks:
                continue
            y = [
                math.log(block.close / origin.close),
                after[0].flow,
                after[0].refill,
                block.at - origin.at,
            ]
            self.store.sample(
                f"{self.symbol}:{origin.at}:{origin.id}",
                self.symbol,
                origin.at,
                block.at,
                list(origin.x),
                y,
                {
                    **origin.context,
                    "policy_version": self.config.version,
                    "costs": origin_cost,
                    "entry": origin.close,
                    "terminal": block.close,
                },
            )

    def on_block(self, block: Block) -> None:
        with self.shared.lock:
            model = self.shared.atlas
            instrument = self.shared.instruments.get(
                self.symbol
            ) or self.shared.public_instruments.get(self.symbol)
            mode = self.shared.mode
            allow = not self.shared.paused and not self.shared.halted and self.shared.broker_ready
        if instrument is None:
            self.manage(block, None, mode)
            self.store.decision(
                block.at, self.symbol, "observe", {"reason": "instrument_metadata_missing"}
            )
            return
        cost = block.x[3] + (instrument.maker + instrument.taker if instrument else 0.0012)
        self._learn(block, cost)
        forecast = model.predict(block.x, self.config.confidence_alpha) if model else None
        model_valid = model is None or (
            0 <= block.at - model.report.get("through", block.at) <= self.config.model_max_age_s
        )
        self.manage(block, forecast if model_valid and self.variant in {"C", "D"} else None, mode)
        if model is None and self.variant in {"C", "D"}:
            self.store.decision(
                block.at, self.symbol, "observe", {"reason": "learning_initial_model"}
            )
            return
        if model and (
            model.report.get("through", block.at) > block.at
            or block.at - model.report.get("through", block.at) > self.config.model_max_age_s
        ):
            self.store.decision(block.at, self.symbol, "observe", {"reason": "model_clock_invalid"})
            return
        if self.contract and self.contract_state == "observing":
            state, reason = self.contract.evaluate(block)
            if state != "observing":
                self.transition(state, block.at, reason)
            if state == "confirmed":
                self._send(block, forecast, instrument, mode, allow, cost)
            if state == "observing":
                return
        if not self.fresh(block.at) or len(self.market.blocks) < self.config.context_blocks:
            return
        if self.variant in {"A", "B"}:
            candidate = baseline(self.symbol, block, self.config, self.market.tick)
            reason = "rule_candidate" if candidate else "rule_abstain"
        else:
            assert forecast is not None
            candidate, reason = propose(
                self.symbol, block, forecast, self.config, cost, self.market.tick
            )
        if candidate:
            self.contract, self.contract_state = candidate, "observing"
            with self.store.transaction() as db:
                db.execute(
                    "INSERT OR IGNORE INTO contracts VALUES(?,?,?,?,?,?)",
                    (
                        candidate.id,
                        self.symbol,
                        block.at,
                        "observing",
                        encode(candidate.payload()),
                        block.at,
                    ),
                )
            if self.variant in {"A", "C"}:
                self.transition("confirmed", block.at, "ablation_without_reaction_gate")
                self._send(block, forecast, instrument, mode, allow, cost)
        self.store.decision(
            block.at,
            self.symbol,
            "atlas",
            {
                "reason": reason,
                "model": forecast.version if forecast else None,
                "lower": forecast.lower if forecast else None,
                "upper": forecast.upper if forecast else None,
                "means": forecast.means if forecast else None,
                "contract": candidate.id if candidate else None,
                "daily": block.context.get("daily", {}),
            },
        )

    def _send(
        self,
        block: Block,
        forecast: Any,
        instrument: Instrument | None,
        mode: str,
        allow: bool,
        cost: float,
    ) -> None:
        with self.shared.admission_lock:
            with self.shared.lock:
                allow = bool(
                    allow
                    and not self.shared.paused
                    and not self.shared.halted
                    and not self.shared.switching
                    and self.shared.broker_ready
                    and mode == self.shared.mode
                )
            self._reserve_entry(block, forecast, instrument, mode, allow, cost)

    def entry_location(self, block: Block) -> bool:
        if self.variant in {"A", "B"}:
            return True
        if self.contract is None:
            return False
        anchors = self.contract.definition.get("pairing", {}).get("anchors", {})
        low, high = anchors.get("low"), anchors.get("high")
        if low is None or high is None or high <= low:
            return False
        price = float(block.context["bid"] if self.contract.side == 1 else block.context["ask"])
        retracement = (high - price if self.contract.side == 1 else price - low) / (high - low)
        return bool(0.5 <= retracement <= 1)

    def _reserve_entry(
        self,
        block: Block,
        forecast: Any,
        instrument: Instrument | None,
        mode: str,
        allow: bool,
        cost: float,
    ) -> None:
        assert self.contract is not None
        entry = float(block.context["bid"] if self.contract.side == 1 else block.context["ask"])
        daily_check = daily_target(
            daily_context(self.market.structure.cache.get("1d", {}), entry, block.at),
            self.contract.side,
            entry,
            self.contract.target,
            max(self.market.tick, float(block.context["ask"]) - float(block.context["bid"])),
            block.at,
        )
        if not allow or instrument is None or not self.news_allows(block.at):
            self.transition("expired", block.at, "entry_not_authorized")
        elif not daily_check["allowed"]:
            self.transition("expired", block.at, daily_check["reason"])
        elif daily_check["limited"]:
            self.transition("expired", block.at, "daily_level_changed_after_confirmation")
        elif not self.entry_location(block):
            self.transition("expired", block.at, "retracement_lost_after_confirmation")
        elif mode == "live" and (
            forecast is None or not forecast.live_ready or self.variant != "D"
        ):
            self.transition("expired", block.at, "model_not_live_qualified")
        elif not self.fresh(block.at):
            self.transition("expired", block.at, "stale_market")
        elif (
            cross_reason := entry_check(
                self.market.cross_market(), self.contract.side, block.at, self.config
            )
        ) != "ready":
            self.transition("expired", block.at, cross_reason)
        elif self.variant in {"C", "D"} and forecast.edge(self.contract.side, cost) <= 0:
            self.transition("expired", block.at, "edge_consumed_while_waiting")
        else:
            factor = 1.0
            with self.shared.lock:
                options = dict(self.shared.external.get(self.symbol, {}))
            iv = float(options.get("weighted_iv") or 0)
            if (
                options.get("available")
                and 0 <= block.at - options["at"] <= self.config.news_stale_s
            ):
                durations = [b.at - b.start for b in self.market.blocks if b.at > b.start]
                if durations and iv > 0 and block.x[9] > 0:
                    annual_realized = block.x[9] * math.sqrt(
                        365.25 * 86400 / (sum(durations) / len(durations))
                    )
                    factor = min(1.0, annual_realized / iv)
                    self.store.decision(
                        block.at,
                        self.symbol,
                        "option_risk_budget",
                        {
                            "factor": factor,
                            "iv": iv,
                            "realized": annual_realized,
                            "gross_gamma": options.get("gross_gamma_1pct"),
                            "dealer_sign": "unknown",
                        },
                    )
            payload, result = reserve(
                self.store,
                mode,
                self.contract,
                instrument,
                self.config,
                block.at,
                entry,
                float(
                    block.context.get(
                        "bid_depth" if self.contract.side == 1 else "ask_depth",
                        block.context["depth"],
                    )
                ),
                block.x[3] * block.close,
                float(block.context["funding"]),
                fraction=factor,
            )
            self.store.decision(
                block.at, self.symbol, "entry_" + result, payload or {"contract": self.contract.id}
            )
            self.shared.broker_wake.set()
            if payload is None:
                self.transition("expired", block.at, result)

    def fresh(self, at: float) -> bool:
        m = self.market
        return bool(
            m.valid
            and entry_check(m.cross_market(), 0, at, self.config) == "ready"
            and 0 <= at - m.book_at <= self.config.max_data_age_s
            and 0 <= at - m.ticker_at <= self.config.account_age_s
            and m.bids
            and m.asks
            and (min(m.asks) - max(m.bids)) / min(m.asks) * 10000 <= self.config.max_spread_bps
        )

    def manage(self, block: Block, forecast: Any, mode: str) -> None:
        accounts = self.store.rows("SELECT * FROM account WHERE mode=?", (mode,))
        if not accounts:
            return
        account = accounts[0]
        if not 0 <= block.at - account["at"] <= self.config.account_age_s:
            return  # Exchange worker retains independent stop/reconciliation protection.
        for pos in json.loads(account["body"])["positions"]:
            if pos["symbol"] != self.symbol or not float(pos.get("size") or 0):
                continue
            rows = self.store.rows(
                "SELECT * FROM orders WHERE mode=? AND symbol=? ORDER BY created DESC LIMIT 1",
                (mode, self.symbol),
            )
            if not rows:
                continue
            order = rows[0]
            spec = json.loads(order["body"])
            side = 1 if pos["side"] == "Buy" else -1
            crossed = side * (block.close - float(spec["stop"])) <= 0
            future_cost = block.x[3]
            with self.shared.lock:
                inst = self.shared.instruments.get(self.symbol)
            if inst:
                future_cost += inst.taker
            with self.shared.lock:
                surprise = any(
                    r.size_rule == "surprise_blackout"
                    and (not r.assets or self.symbol in r.assets or "ALL" in r.assets)
                    and r.known_at.timestamp()
                    <= block.at
                    <= r.event_time.timestamp() + self.config.news_post_minutes * 60
                    for r in self.shared.calendar
                )
            should_exit = (
                crossed
                or surprise
                or (forecast is not None and forecast.edge(side, future_cost) <= 0)
            )
            if should_exit:
                self.store.command(
                    "contract-exit-" + order["id"],
                    mode,
                    self.symbol,
                    "flatten",
                    block.at,
                    {
                        "reason": "refuted"
                        if crossed
                        else "news_surprise"
                        if surprise
                        else "hold_edge_gone"
                    },
                )
                self.shared.broker_wake.set()
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE contracts SET state='refuted',updated=? WHERE id=?",
                        (block.at, order["contract"]),
                    )
            elif forecast is not None:
                # A volatility trail can tighten only; the executor rechecks the
                # actual venue position/MarkPrice before changing the stop.
                excursion = abs(forecast.lower if side == 1 else forecast.upper)
                distance = max(self.market.tick, block.close * math.expm1(min(excursion, 1.0)))
                stop = block.close - side * distance
                self.store.command(
                    f"trail-{order['id']}-{block.id}",
                    mode,
                    self.symbol,
                    "stop",
                    block.at,
                    {"stop": stop, "reason": "conditional_tail"},
                )
                self.shared.broker_wake.set()
