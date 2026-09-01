"""Journal-only 3-candle FVG mark. Not a zone method. Not a jury voice.

NinjaTrader textbook (2026): three consecutive candles; bullish when
candle3.low > candle1.high; bearish when candle3.high < candle1.low.
A hole in close_ts is not a pattern. Unknown tf → None. Short history → None.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from capitalizator.zones.model import Bar


def _step(tf: str) -> timedelta | None:
    if tf.endswith("m") and tf[:-1].isdigit():
        return timedelta(minutes=int(tf[:-1]))
    if tf.endswith("h") and tf[:-1].isdigit():
        return timedelta(hours=int(tf[:-1]))
    if tf.endswith("d") and tf[:-1].isdigit():
        return timedelta(days=int(tf[:-1]))
    return None


def fvg_present(
    bars: Sequence[Bar],
    *,
    symbol: str,
    tf: str,
    close_ts: datetime,
) -> bool | None:
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
    step = _step(tf)
    if step is None:
        return None
    if mid.close_ts - first.close_ts != step or third.close_ts - mid.close_ts != step:
        return None
    bullish = first.high < third.low
    bearish = first.low > third.high
    return bullish or bearish
