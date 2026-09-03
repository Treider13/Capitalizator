"""1.5.2 — day −3% / week −6% / −25% from peak / liq → no new entry.

Does not flatten. Does not place an order. Counters are on the equity we are given
(demo or paper). Live mainnet equity is not read here.

PHASE-BUILD artifact: Halts.state(day_pnl_pct, week_pnl_pct, dd_from_peak, liq_flag).
Once halted, reason sticks. Closing an open idea is RiskEngine.on_flat, not this class.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DAY = Decimal("-0.03")
WEEK = Decimal("-0.06")
PEAK = Decimal("-0.25")


@dataclass(frozen=True)
class Halt:
    halted: bool
    reason: str


class Halts:
    def __init__(
        self,
        *,
        start_equity: Decimal,
        peak: Decimal | None = None,
        day: Decimal = DAY,
        week: Decimal = WEEK,
        peak_kill: Decimal = PEAK,
    ) -> None:
        if start_equity <= 0:
            raise ValueError("start_equity must be > 0")
        self.day_start = start_equity
        self.week_start = start_equity
        self.peak = peak if peak is not None else start_equity
        if self.peak <= 0:
            raise ValueError("peak must be > 0")
        if day >= 0 or week >= 0 or peak_kill >= 0:
            raise ValueError("halt thresholds must be negative")
        # Operator knobs (risk_config); defaults are the gates.yaml f5 numbers.
        self.day_limit = day
        self.week_limit = week
        self.peak_limit = peak_kill
        self.halted = False
        self.reason = ""

    def new_day(self, equity: Decimal) -> None:
        if equity <= 0:
            raise ValueError("equity must be > 0")
        self.day_start = equity
        if self.halted and self.reason == "day":
            # A day halt ends with the day; week/peak/liq need a human release().
            self.halted = False
            self.reason = ""

    def new_week(self, equity: Decimal) -> None:
        if equity <= 0:
            raise ValueError("equity must be > 0")
        self.week_start = equity
        if self.halted and self.reason == "week":
            self.halted = False
            self.reason = ""

    def release(self, *, ack: bool) -> None:
        """Human release of a sticky halt (peak / liq / equity). Needs an explicit ack."""
        if not ack:
            raise ValueError("release needs ack")
        self.halted = False
        self.reason = ""

    def mark_liq(self) -> None:
        self.halted = True
        self.reason = "liq"

    def state(
        self,
        day_pnl_pct: Decimal,
        week_pnl_pct: Decimal,
        dd_from_peak: Decimal,
        liq_flag: bool,
    ) -> Halt:
        got = _eval(
            day_pnl_pct=day_pnl_pct,
            week_pnl_pct=week_pnl_pct,
            dd_from_peak=dd_from_peak,
            liq_flag=liq_flag,
            day=self.day_limit,
            week=self.week_limit,
            peak=self.peak_limit,
        )
        if self.halted:
            return Halt(True, self.reason)
        if got.halted:
            self.halted = True
            self.reason = got.reason
        return got

    def update(self, equity: Decimal) -> None:
        if self.halted:
            return
        if equity <= 0:
            self.halted = True
            self.reason = "equity"
            return
        if equity > self.peak:
            self.peak = equity
        day = (equity - self.day_start) / self.day_start
        week = (equity - self.week_start) / self.week_start
        dd = (equity - self.peak) / self.peak
        self.state(
            day_pnl_pct=day,
            week_pnl_pct=week,
            dd_from_peak=dd,
            liq_flag=False,
        )

    def remaining_frac(self, equity: Decimal) -> dict[str, Decimal]:
        """How much more of each reference equity can be lost before that tap.

        Positive = room left. At the start of the day with the default −3% tap
        this is 0.03. Already down 1% → 0.02. A trade whose risk_frac is larger
        is a warning (the tap still fires after the loss), not a silent shrink.
        """
        if equity <= 0:
            raise ValueError("equity must be > 0")
        day_used = (self.day_start - equity) / self.day_start
        week_used = (self.week_start - equity) / self.week_start
        peak_used = (self.peak - equity) / self.peak
        return {
            "day": abs(self.day_limit) - day_used,
            "week": abs(self.week_limit) - week_used,
            "peak": abs(self.peak_limit) - peak_used,
        }

    def allow_entry(self) -> bool:
        return not self.halted


def _eval(
    *,
    day_pnl_pct: Decimal,
    week_pnl_pct: Decimal,
    dd_from_peak: Decimal,
    liq_flag: bool,
    day: Decimal = DAY,
    week: Decimal = WEEK,
    peak: Decimal = PEAK,
) -> Halt:
    if liq_flag:
        return Halt(True, "liq")
    if day_pnl_pct <= day:
        return Halt(True, "day")
    if week_pnl_pct <= week:
        return Halt(True, "week")
    if dd_from_peak <= peak:
        return Halt(True, "peak")
    return Halt(False, "")
