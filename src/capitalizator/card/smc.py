"""ICT/SMC labels for contour B: Order Block and Break of Structure.

Rewritten in-repo after joshyattridge/smart-money-concepts. Labels only.
None when the series cannot confirm a swing. Never an A entry engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from capitalizator.card.params import SWEEP_FRACTAL_N
from capitalizator.card.sweep import fractals
from capitalizator.zones.model import Bar

SmcSide = Literal["bull", "bear"]


def bos_status(bars: Sequence[Bar], *, fractal_n: int = SWEEP_FRACTAL_N) -> SmcSide | None:
    """Close beyond the last confirmed swing high/low."""
    if len(bars) < fractal_n * 2 + 2:
        return None
    highs, lows = fractals(bars, n=fractal_n)
    last = bars[-1]
    last_high_i = highs[-1] if highs else None
    last_low_i = lows[-1] if lows else None
    bull = (
        last_high_i is not None
        and last_high_i < len(bars) - 1
        and last.close > bars[last_high_i].high
    )
    bear = (
        last_low_i is not None
        and last_low_i < len(bars) - 1
        and last.close < bars[last_low_i].low
    )
    if bull and bear:
        if last_high_i is not None and last_low_i is not None:
            return "bull" if last_high_i >= last_low_i else "bear"
        return "bull" if bull else "bear"
    if bull:
        return "bull"
    if bear:
        return "bear"
    return None


def ob_status(bars: Sequence[Bar], *, fractal_n: int = SWEEP_FRACTAL_N) -> SmcSide | None:
    """Last opposite candle before the BOS impulse. None if BOS is missing."""
    side = bos_status(bars, fractal_n=fractal_n)
    if side is None:
        return None
    for bar in reversed(bars[:-1]):
        if side == "bull" and bar.close < bar.open:
            return "bull"
        if side == "bear" and bar.close > bar.open:
            return "bear"
    return None
