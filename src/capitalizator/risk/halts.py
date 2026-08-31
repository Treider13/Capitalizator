"""1.5.2 — day −3% / week −6% / −25% from peak / liq → no new entry.

Does not flatten. Does not place an order. Counters are on the equity we are given
(demo or paper). Live mainnet equity is not read here.
"""

from __future__ import annotations

from decimal import Decimal

DAY = Decimal("-0.03")
WEEK = Decimal("-0.06")
PEAK = Decimal("-0.25")


class Halts:
    def __init__(self, *, start_equity: Decimal, peak: Decimal | None = None) -> None:
        if start_equity <= 0:
            raise ValueError("start_equity must be > 0")
        self.day_start = start_equity
        self.week_start = start_equity
        self.peak = peak if peak is not None else start_equity
        if self.peak <= 0:
            raise ValueError("peak must be > 0")
        self.halted = False
        self.reason = ""

    def mark_liq(self) -> None:
        self.halted = True
        self.reason = "liq"

    def update(self, equity: Decimal) -> None:
        if equity <= 0:
            self.halted = True
            self.reason = "equity"
            return
        if equity > self.peak:
            self.peak = equity
        day = (equity - self.day_start) / self.day_start
        week = (equity - self.week_start) / self.week_start
        dd = (equity - self.peak) / self.peak
        if day <= DAY:
            self.halted = True
            self.reason = "day"
        elif week <= WEEK:
            self.halted = True
            self.reason = "week"
        elif dd <= PEAK:
            self.halted = True
            self.reason = "peak"

    def allow_entry(self) -> bool:
        return not self.halted
