"""Three-candle FVG — one implementation for the journal mark and the B card.

NinjaTrader textbook (2026): three consecutive candles; bullish when
candle3.low > candle1.high; bearish when candle3.high < candle1.low.
Consecutive means consecutive: a hole in close_ts is not a pattern (a gap in the
tape is not a fair-value gap). Not a zone method. Not a jury voice.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from capitalizator.zones.model import Bar


def _step(tf: str) -> timedelta | None:
    if tf.endswith("m") and tf[:-1].isdigit():
        return timedelta(minutes=int(tf[:-1]))
    if tf.endswith("h") and tf[:-1].isdigit():
        return timedelta(hours=int(tf[:-1]))
    if tf.endswith("d") and tf[:-1].isdigit():
        return timedelta(days=int(tf[:-1]))
    return None


def _contiguous(first: Bar, mid: Bar, third: Bar) -> bool:
    step = _step(third.tf)
    if step is None:
        return False
    return mid.close_ts - first.close_ts == step and third.close_ts - mid.close_ts == step


def gap_of(first: Bar, third: Bar) -> tuple[Decimal, Decimal] | None:
    """(low, high) of the gap band, or None."""
    if first.high < third.low:
        return first.high, third.low
    if first.low > third.high:
        return third.high, first.low
    return None


def latest_fvg(bars: Sequence[Bar]) -> tuple[Decimal, Decimal] | None:
    """Most recent three-candle gap among *consecutive* bars of one symbol/tf."""
    series = sorted(bars, key=lambda b: b.close_ts)
    found: tuple[Decimal, Decimal] | None = None
    for i in range(2, len(series)):
        first, mid, third = series[i - 2], series[i - 1], series[i]
        if first.symbol != third.symbol or first.tf != third.tf or mid.tf != third.tf:
            continue
        if not _contiguous(first, mid, third):
            continue
        gap = gap_of(first, third)
        if gap is not None:
            found = gap
    return found


def fvg_present(
    bars: Sequence[Bar],
    *,
    symbol: str,
    tf: str,
    close_ts: datetime,
) -> bool | None:
    """Journal mark: does the bar closing at `close_ts` complete a gap? None = cannot say."""
    series = [
        b
        for b in bars
        if b.symbol == symbol and b.tf == tf and b.close_ts <= close_ts
    ]
    series.sort(key=lambda b: b.close_ts)
    if len(series) < 3:
        return None
    first, mid, third = series[-3:]
    if third.close_ts != close_ts:
        return None
    if _step(tf) is None or not _contiguous(first, mid, third):
        return None
    return gap_of(first, third) is not None
