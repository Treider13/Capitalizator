"""3.13.4 — wick beyond the zone, close back inside → tag failed_break.

This is a label, not an entry. Not breakout. Not bounce.
Does not send an order. Does not mix into breakout counts.
"""

from __future__ import annotations

from capitalizator.zones.model import Bar, Zone

TAG = "failed_break"


def wick_beyond(*, zone: Zone, bar: Bar) -> bool:
    """Wick traded through the zone band. Same atom as FailedBreak. Not an entry."""
    if bar.symbol != zone.symbol:
        return False
    if zone.side == "support":
        return bar.low < zone.lo
    return bar.high > zone.hi


def sweep_wick(*, zone: Zone, bar: Bar) -> bool:
    """Journal column: wick beyond the zone. Close may be inside or through."""
    return wick_beyond(zone=zone, bar=bar)


class FailedBreak:
    @staticmethod
    def tag(*, zone: Zone, bar: Bar) -> str | None:
        if bar.symbol != zone.symbol:
            return None
        inside = zone.lo <= bar.close <= zone.hi
        if not inside:
            return None
        return TAG if wick_beyond(zone=zone, bar=bar) else None

    @staticmethod
    def counts_as_breakout(tag: str) -> bool:
        return False

    @staticmethod
    def counts_as_bounce(tag: str) -> bool:
        return False
