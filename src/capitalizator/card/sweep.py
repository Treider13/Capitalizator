"""Liquidity sweep label for contour B. Williams fractals. Not an A engine.

Wick through a local high/low and close back → done.
Through and close still beyond → pending.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.card.live import SweepStatus
from capitalizator.card.params import SWEEP_FRACTAL_N, SWEEP_LOOKBACK
from capitalizator.zones.model import Bar


def sweep_status(
    bars: Sequence[Bar],
    *,
    lookback: int = SWEEP_LOOKBACK,
    fractal_n: int = SWEEP_FRACTAL_N,
) -> SweepStatus:
    work = list(bars[-lookback:]) if lookback > 0 else list(bars)
    if len(work) < fractal_n * 2 + 2:
        return "none"
    tester = work[-1]
    body = work[:-1]
    highs, lows = fractals(body, n=fractal_n)
    status: SweepStatus = "none"
    if highs:
        level = body[highs[-1]].high
        swept = _sweep_level(tester, level, side="high")
        if swept is not None:
            status = swept
    if lows:
        level = body[lows[-1]].low
        swept = _sweep_level(tester, level, side="low")
        if swept == "pending" or (swept is not None and status != "pending"):
            status = swept
    return status


def fractals(bars: Sequence[Bar], *, n: int = SWEEP_FRACTAL_N) -> tuple[list[int], list[int]]:
    """Confirmed Williams fractal indexes. Needs `n` bars on each side."""
    highs: list[int] = []
    lows: list[int] = []
    if len(bars) < n * 2 + 1:
        return highs, lows
    for i in range(n, len(bars) - n):
        if _strict_high(bars, i, n):
            highs.append(i)
        if _strict_low(bars, i, n):
            lows.append(i)
    return highs, lows


def _strict_high(bars: Sequence[Bar], i: int, n: int) -> bool:
    px = bars[i].high
    return all(px > bars[i + k].high for k in range(-n, n + 1) if k != 0)


def _strict_low(bars: Sequence[Bar], i: int, n: int) -> bool:
    px = bars[i].low
    return all(px < bars[i + k].low for k in range(-n, n + 1) if k != 0)


def _sweep_level(bar: Bar, level: Decimal, *, side: str) -> SweepStatus | None:
    if side == "high":
        if bar.high <= level:
            return None
        return "done" if bar.close < level else "pending"
    if bar.low >= level:
        return None
    return "done" if bar.close > level else "pending"
