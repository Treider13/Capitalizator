"""Account state the risk gates read from (D-09/D-10/D-13).

One object owns: equity (paper until a wallet is read), open ideas per symbol,
day/week roll for the halts, the per-session intent budget. RiskEngine and Halts
were never told about opens / equity before — `allow_entry()` was always True.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from capitalizator.ops.knowledge import Knowledge
from capitalizator.risk.budget import SessionBudget
from capitalizator.risk.config import RiskConfig
from capitalizator.risk.correlation import CorrelationGuard
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, Position, RiskEngine
from capitalizator.types import require_utc

MSK = ZoneInfo("Europe/Moscow")


class PersistentBudget(SessionBudget):
    """SessionBudget whose count survives a restart (meta budget:<session>)."""

    def __init__(self, *, key: str, max_n: int, knowledge: Knowledge | None) -> None:
        super().__init__(max_n=max_n)
        self.key = key
        self._knowledge = knowledge
        if knowledge is not None and knowledge.available():
            raw = knowledge.meta(f"budget:{key}")
            if raw is not None and raw.isdigit():
                self.n = int(raw)

    def on_intent(self) -> None:
        super().on_intent()
        if self._knowledge is not None and self._knowledge.available():
            self._knowledge.set_meta(f"budget:{self.key}", str(self.n))


@dataclass
class OpenIdea:
    symbol: str
    side: str
    qty: Decimal
    entry: Decimal
    stop: Decimal
    opened_at: datetime
    intent_id: int | None = None
    source: str = "paper"


@dataclass
class Account:
    config: RiskConfig
    knowledge: Knowledge | None = None
    equity: Decimal = field(default=Decimal("0"))
    equity_source: str = "paper"
    equity_at: datetime | None = None
    realized_pnl: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    funding_paid: Decimal = Decimal("0")
    open: dict[str, OpenIdea] = field(default_factory=dict)
    risk: RiskEngine = field(default_factory=RiskEngine)
    halts: Halts | None = None
    # One idea per correlation group (risk/correlation.py). None = rule off (tests).
    correlation: CorrelationGuard | None = None
    _budgets: dict[str, PersistentBudget] = field(default_factory=dict)
    _day: str | None = None
    _week: str | None = None
    source_switches: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.equity <= 0:
            self.equity = self.config.paper_equity
        self.risk = RiskEngine(max_open=self.config.max_open_positions)
        if self.correlation is None and self.config.max_open_positions > 1:
            self.correlation = CorrelationGuard.load(threshold=self.config.corr_block_threshold)
        if self.halts is None:
            self.halts = Halts(
                start_equity=self.equity,
                day=self.config.day_halt,
                week=self.config.week_halt,
                peak_kill=self.config.peak_kill,
            )

    # --- clocks -------------------------------------------------------------
    def roll(self, now: datetime) -> None:
        """Day/week starts for the halts — in the desk's session calendar (Moscow),
        the same day the intent budget uses. A UTC roll put the −3% day and the
        3-entry day in different days (audit §3.5)."""
        local = require_utc(now).astimezone(MSK)
        day = local.date().isoformat()
        week = f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
        assert self.halts is not None
        if self._day is not None and day < self._day:
            # replayed history after a restart must not re-baseline the day or lift a
            # day halt (audit A3): the calendar only moves forward
            return
        changed = False
        if self._day != day:
            if self._day is not None:
                self.halts.new_day(self.equity)
            self._day = day
            changed = True
        if self._week != week:
            if self._week is not None:
                self.halts.new_week(self.equity)
            self._week = week
            changed = True
        if changed:
            self._persist()

    def budget(self, now: datetime, *, key: str, max_n: int | None = None) -> PersistentBudget:
        """Intent budget for a session key.

        The desk passes the window's `budget_key` (`YYYY-MM-DD:window`, UTC) and the
        window's cap; the operator's `max_intents_per_session` stays the ceiling for
        any single key. Stale keys are dropped when a newer one appears (keys sort
        chronologically). There is no keyless form: a second calendar (the old
        Moscow-day key) next to the UTC window keys was two budgets for one desk.
        """
        require_utc(now)
        budget_key = key
        cap = self.config.max_intents_per_session
        if max_n is not None:
            cap = max(0, min(cap, max_n))
        got = self._budgets.get(budget_key)
        if got is None or got.max_n != cap:
            got = PersistentBudget(key=budget_key, max_n=cap, knowledge=self.knowledge)
            self._budgets[budget_key] = got
            day = budget_key.split(":", 1)[0]
            for stale in [k for k in self._budgets if k.split(":", 1)[0] < day]:
                del self._budgets[stale]
        return got

    def set_equity(self, equity: Decimal, *, source: str, now: datetime) -> None:
        if equity <= 0:
            raise ValueError("equity must be > 0")
        assert self.halts is not None
        if source != self.equity_source:
            # Source switch (paper → venue wallet, testnet → live): the old baselines
            # belong to another number. Comparing the first wallet reading with the
            # paper equity tripped a false day halt (found by test). Re-baseline the
            # *numbers* — but a halt that is already on stays on: releasing a kill
            # switch is an operator act (`release_halts` with ack), never a side
            # effect of reading a wallet (audit B3).
            self.halts.day_start = equity
            self.halts.week_start = equity
            self.halts.peak = equity
            self.source_switches.append(
                {
                    "at": require_utc(now).isoformat(),
                    "from": self.equity_source,
                    "to": source,
                    "equity": str(equity),
                    "halted": self.halts.halted,
                }
            )
            del self.source_switches[:-20]
        self.equity = equity
        self.equity_source = source
        self.equity_at = require_utc(now)
        self.halts.update(equity)
        self._persist()

    def apply_pnl(
        self,
        *,
        pnl: Decimal,
        fees: Decimal,
        funding: Decimal,
        now: datetime,
        source: str = "paper",
    ) -> None:
        self.realized_pnl += pnl
        self.fees_paid += fees
        self.funding_paid += funding
        self.set_equity(self.equity + pnl - fees - funding, source=source, now=now)

    # --- positions -----------------------------------------------------------
    def allow_entry(self, symbol: str) -> tuple[bool, str]:
        assert self.halts is not None
        if not self.halts.allow_entry():
            return False, f"halt:{self.halts.reason}"
        if symbol in self.open:
            return False, "position_open_same_symbol"
        if len(self.open) >= self.config.max_open_positions:
            return False, "max_open_positions"
        if self.correlation is not None and self.open:
            blocked, why = self.correlation.blocks(symbol, self.open.keys())
            if blocked:
                return False, why
        return True, "ok"

    def sizing_equity(self) -> Decimal:
        """The slice the desk may size against (participating_share × equity)."""
        return self.config.participating_equity(self.equity)

    def on_open(self, intent: Intent, *, now: datetime, intent_id: int | None = None) -> None:
        if intent.qty is None or intent.qty <= 0:
            raise ValueError("open needs a sized intent")
        self.risk.on_open(intent)
        self.open[intent.symbol] = OpenIdea(
            symbol=intent.symbol,
            side=intent.side,
            qty=intent.qty,
            entry=intent.entry,
            stop=intent.stop,
            opened_at=require_utc(now),
            intent_id=intent_id,
        )
        self._persist()

    def on_flat(self, symbol: str) -> None:
        self.open.pop(symbol, None)
        self.risk.on_flat(symbol)
        self._persist()

    def positions(self) -> list[Position]:
        return list(self.risk.open_positions())

    # --- persistence -----------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        assert self.halts is not None
        return {
            "equity": str(self.equity),
            "equity_source": self.equity_source,
            "equity_at": self.equity_at.isoformat() if self.equity_at else None,
            "realized_pnl": str(self.realized_pnl),
            "fees_paid": str(self.fees_paid),
            "funding_paid": str(self.funding_paid),
            "peak": str(self.halts.peak),
            "day_start": str(self.halts.day_start),
            "week_start": str(self.halts.week_start),
            "drawdown_from_peak": str((self.equity - self.halts.peak) / self.halts.peak),
            "day_pnl_pct": str((self.equity - self.halts.day_start) / self.halts.day_start),
            "week_pnl_pct": str((self.equity - self.halts.week_start) / self.halts.week_start),
            "halted": self.halts.halted,
            "halt_reason": self.halts.reason,
            "open": [
                {
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": str(o.qty),
                    "entry": str(o.entry),
                    "stop": str(o.stop),
                    "opened_at": o.opened_at.isoformat(),
                    "source": o.source,
                    "intent_id": o.intent_id,
                }
                for o in self.open.values()
            ],
            "source_switches": list(self.source_switches),
            "day_key": self._day,
            "week_key": self._week,
            "config_id": self.config.config_id,
        }

    def persist(self) -> None:
        if self.knowledge is None or not self.knowledge.available():
            return
        self.knowledge.set_meta("account", json.dumps(self.snapshot(), sort_keys=True))

    # kept for callers that still use the private name
    _persist = persist

    @classmethod
    def load(
        cls,
        knowledge: Knowledge | None,
        config: RiskConfig,
        *,
        now: datetime | None = None,
    ) -> Account:
        acct = cls(config=config, knowledge=knowledge)
        raw = knowledge.meta("account") if knowledge is not None and knowledge.available() else None
        if raw:
            try:
                snap = json.loads(raw)
                acct.equity = Decimal(str(snap["equity"]))
                acct.equity_source = str(snap.get("equity_source") or "paper")
                acct.realized_pnl = Decimal(str(snap.get("realized_pnl") or "0"))
                acct.fees_paid = Decimal(str(snap.get("fees_paid") or "0"))
                acct.funding_paid = Decimal(str(snap.get("funding_paid") or "0"))
                acct.halts = Halts(
                    start_equity=Decimal(str(snap.get("day_start") or acct.equity)),
                    peak=Decimal(str(snap.get("peak") or acct.equity)),
                    day=config.day_halt,
                    week=config.week_halt,
                    peak_kill=config.peak_kill,
                )
                acct.halts.week_start = Decimal(str(snap.get("week_start") or acct.equity))
                if snap.get("halted"):
                    acct.halts.halted = True
                    acct.halts.reason = str(snap.get("halt_reason") or "")
                acct.source_switches = list(snap.get("source_switches") or [])
                acct._day = snap.get("day_key") or None
                acct._week = snap.get("week_key") or None
                # Open ideas survive a restart: `allow_entry` must know about the
                # position the venue still holds (audit B3: "one position persisted"
                # was written but never read back).
                for raw_open in snap.get("open") or []:
                    idea = OpenIdea(
                        symbol=str(raw_open["symbol"]),
                        side=str(raw_open["side"]),
                        qty=Decimal(str(raw_open["qty"])),
                        entry=Decimal(str(raw_open["entry"])),
                        stop=Decimal(str(raw_open["stop"])),
                        opened_at=datetime.fromisoformat(str(raw_open["opened_at"])),
                        intent_id=(
                            None if raw_open.get("intent_id") is None
                            else int(raw_open["intent_id"])
                        ),
                        source=str(raw_open.get("source") or "paper"),
                    )
                    acct.open[idea.symbol] = idea
                    tp = (
                        idea.entry + (idea.entry - idea.stop)
                        if idea.side == "buy"
                        else idea.entry - (idea.stop - idea.entry)
                    )
                    acct.risk.on_open(
                        Intent(
                            symbol=idea.symbol,
                            side=idea.side,  # type: ignore[arg-type]
                            entry=idea.entry,
                            stop=idea.stop,
                            tp=tp,
                            tag="restored",
                            qty=idea.qty,
                        )
                    )
            except (KeyError, ValueError, ArithmeticError, json.JSONDecodeError):
                pass
        acct.roll(now if now is not None else datetime.now(tz=UTC))
        return acct
