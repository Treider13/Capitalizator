"""CAV — chart vote on a *closed* bar vs a pre-drawn zone. Not a trade.

INVENTION-JURY.md: REJECT / THROUGH / COMPRESS / DRIFT / NOISE.
THROUGH and REJECT only after close_ts < t. Unclosed bar → NOISE.
HTF against the bounce side → NOISE. Bar that does not touch the zone → NOISE.
COMPRESS uses range < ATR of the last 14 closed bars (k=1, the unit in the formula).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal

from capitalizator.types import require_utc
from capitalizator.zones.map import HtfBias
from capitalizator.zones.model import Bar, Zone

CavLabel = Literal["REJECT", "THROUGH", "COMPRESS", "DRIFT", "NOISE"]


def _touches(bar: Bar, zone: Zone) -> bool:
    return bar.low <= zone.hi and bar.high >= zone.lo


def _atr(bars: Sequence[Bar], n: int = 14) -> Decimal | None:
    if len(bars) < n + 1:
        return None
    window = bars[-(n + 1) :]
    total = Decimal("0")
    prev = window[0]
    for bar in window[1:]:
        tr = max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        total += tr
        prev = bar
    return total / n


def label(
    zone: Zone,
    bar: Bar,
    *,
    t: datetime,
    htf_bias: HtfBias,
    closed_bars: Sequence[Bar] = (),
) -> CavLabel:
    """One label. Does not open size. Mid-range bar that misses the zone is NOISE."""
    when = require_utc(t)
    if bar.close_ts >= when:
        return "NOISE"
    if not _touches(bar, zone):
        return "NOISE"
    bounce_side = "long" if zone.side == "support" else "short"
    if htf_bias not in {"unknown", "box"} and htf_bias != bounce_side:
        return "NOISE"
    if zone.side == "support":
        through = bar.close < zone.lo
        wick_in = bar.low <= zone.hi
        close_inside = bar.close >= zone.lo
    else:
        through = bar.close > zone.hi
        wick_in = bar.high >= zone.lo
        close_inside = bar.close <= zone.hi
    if through:
        return "THROUGH"
    if wick_in and close_inside and (
        (zone.side == "support" and bar.low < zone.lo)
        or (zone.side == "resistance" and bar.high > zone.hi)
    ):
        return "REJECT"
    atr = _atr([b for b in closed_bars if b.close_ts < when and b.tf == bar.tf])
    if atr is not None and (bar.high - bar.low) < atr and zone.lo <= bar.close <= zone.hi:
        return "COMPRESS"
    if zone.lo <= bar.close <= zone.hi:
        return "DRIFT"
    return "NOISE"
