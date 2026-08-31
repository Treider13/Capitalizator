"""3.13.4 — wick beyond the zone, close back inside → tag failed_break.

This is a label, not an entry. Not breakout. Not bounce.
Does not send an order. Does not mix into breakout counts.
"""

from __future__ import annotations

from capitalizator.zones.model import Bar, Zone

TAG = "failed_break"


class FailedBreak:
    @staticmethod
    def tag(*, zone: Zone, bar: Bar) -> str | None:
        if bar.symbol != zone.symbol:
            return None
        inside = zone.lo <= bar.close <= zone.hi
        if not inside:
            return None
        if zone.side == "support":
            beyond = bar.low < zone.lo
        else:
            beyond = bar.high > zone.hi
        return TAG if beyond else None

    @staticmethod
    def counts_as_breakout(tag: str) -> bool:
        return False

    @staticmethod
    def counts_as_bounce(tag: str) -> bool:
        return False
