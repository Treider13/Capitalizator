"""Bar width vs ATR on the last gap-split segment. Journal, not size.

w_now = range / ATR(14). w_rank is the PIT share of earlier same-zone
touches with a strictly smaller w_now. n < 20 → None.
Does not open size. Does not vote.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from capitalizator.patterns.bar_quality import atr, last_gap_segment
from capitalizator.types import require_utc
from capitalizator.zones.model import Bar

RANK_MIN = 20


@dataclass(frozen=True)
class WidthSample:
    """One historical width observation. Not a Touch — patterns does not import memory."""

    zone_id: str
    ts: datetime
    w_now: Decimal

    def __post_init__(self) -> None:
        require_utc(self.ts)
        if self.w_now < 0:
            raise ValueError("w_now must be >= 0")


def width_now(bar: Bar, atr_value: Decimal | None) -> Decimal | None:
    if atr_value is None or atr_value <= 0:
        return None
    return (bar.high - bar.low) / atr_value


def width_now_from_history(
    bar: Bar,
    history: Sequence[Bar],
    *,
    t: datetime,
) -> Decimal | None:
    """w_now on the last gap-split segment that closed before this bar.

    Unclosed bar (close_ts >= t) → None: range is not a fact yet.
    """
    when = require_utc(t)
    if bar.close_ts >= when:
        return None
    return width_now(bar, atr(last_gap_segment(history, bar, t=when)))


def width_rank(
    *,
    zone_id: str,
    now: datetime,
    w_now: Decimal,
    history: Sequence[WidthSample],
) -> Decimal | None:
    """PIT percentile vs priors of the same zone_id with ts < now. n < 20 → None."""
    when = require_utc(now)
    if w_now < 0:
        raise ValueError("w_now must be >= 0")
    priors = [row for row in history if row.zone_id == zone_id and row.ts < when]
    if len(priors) < RANK_MIN:
        return None
    less = sum(1 for row in priors if row.w_now < w_now)
    return Decimal(less) / Decimal(len(priors))
