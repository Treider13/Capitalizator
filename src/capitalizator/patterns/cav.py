"""CAV — chart vote on a *closed* bar vs a pre-drawn zone. Not a trade.

INVENTION-JURY.md: REJECT / THROUGH / COMPRESS / DRIFT / NOISE.
THROUGH and REJECT only after close_ts < t. Unclosed bar → NOISE.
stagnant / illiquid K-line → NOISE. A jump gap is not NOISE; it only splits ATR.
HTF against the bounce side → NOISE. Bar that does not touch the zone → NOISE.
COMPRESS uses range < mean TR of the last 14 steps after the last gap
(needs 15 closed bars in that segment; k=1). A jump into the labeled bar
starts a new segment — old ATR is not borrowed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from capitalizator.patterns.bar_quality import (
    ILLIQUID,
    STAGNANT,
    atr,
    classify_bar_quality,
    last_gap_segment,
)
from capitalizator.types import require_utc
from capitalizator.zones.map import HtfBias
from capitalizator.zones.model import Bar, Zone

CavLabel = Literal["REJECT", "THROUGH", "COMPRESS", "DRIFT", "NOISE"]


def _touches(bar: Bar, zone: Zone) -> bool:
    return bar.low <= zone.hi and bar.high >= zone.lo


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
    quality = classify_bar_quality(closed_bars, bar, t=when)
    if quality in {STAGNANT, ILLIQUID}:
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
    atr_value = atr(last_gap_segment(closed_bars, bar, t=when))
    if (
        atr_value is not None
        and (bar.high - bar.low) < atr_value
        and zone.lo <= bar.close <= zone.hi
    ):
        return "COMPRESS"
    if zone.lo <= bar.close <= zone.hi:
        return "DRIFT"
    return "NOISE"
