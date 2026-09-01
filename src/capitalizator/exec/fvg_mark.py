"""Journal-only 3-candle FVG mark. Not a zone method. Not a jury voice.

ICT public definition (Huddleston / common 2026 writeups, NinjaTrader FairValueGapICT):
bullish gap when candle3.low > candle1.high; bearish when candle3.high < candle1.low.
Fewer than 3 closed bars of the same symbol/tf → None, not False.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from capitalizator.zones.model import Bar


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
    first, _mid, third = series[-3:]
    if third.close_ts != close_ts:
        return None
    bullish = first.high < third.low
    bearish = first.low > third.high
    return bullish or bearish
