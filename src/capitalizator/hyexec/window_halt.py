"""Window book-keeping. Asia PnL does not close overlap. Day −3% still does."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.risk.halts import DAY, PEAK, WEEK

APLUS_CUT = Decimal("-0.015")


class WindowHalt:
    def __init__(self, *, start_equity: Decimal) -> None:
        if start_equity <= 0:
            raise ValueError("start_equity must be > 0")
        self.start = start_equity
        self.equity = start_equity
        self.peak = start_equity
        self.reason = ""

    def note_window(self, window: str, equity: Decimal) -> None:
        if not window:
            raise ValueError("window required")
        if equity <= 0:
            self.equity = equity
            self.reason = "equity"
            return
        self.equity = equity
        if equity > self.peak:
            self.peak = equity
        day = (equity - self.start) / self.start
        week = (equity - self.start) / self.start
        dd = (equity - self.peak) / self.peak
        if day <= DAY:
            self.reason = "day"
        elif week <= WEEK:
            self.reason = "week"
        elif dd <= PEAK:
            self.reason = "peak"

    def day_pnl(self) -> Decimal:
        return (self.equity - self.start) / self.start

    def allow_entry(self, window: str) -> bool:
        if not window:
            raise ValueError("window required")
        return self.reason == ""

    def allow_aplus(self, window: str) -> bool:
        if not self.allow_entry(window):
            return False
        if window != "overlap":
            return False
        return self.day_pnl() > APLUS_CUT
