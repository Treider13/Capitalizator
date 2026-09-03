"""Liquidity sweep label for contour B. Williams fractals. Not an A engine.

Wick through a local high/low and close back → done.
Through and close still beyond → pending.

Side matters (audit §6): the "fuel" for a LONG is the liquidity *below* — stops
under the last swing low taken and price back above it. A sweep of the last swing
high is fuel for a SHORT and says nothing for a long. `sweep_status_for(side)`
reads the relevant extreme; `sweep_status()` keeps the side-agnostic legacy
reading (either extreme) for the journal column.
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


def sweep_status_for(
    bars: Sequence[Bar],
    side: str,
    *,
    lookback: int = SWEEP_LOOKBACK,
    fractal_n: int = SWEEP_FRACTAL_N,
) -> SweepStatus:
    """Long ('buy'): the last confirmed swing LOW must have been swept (wick below,
    close back above) → done; wick below and close still below → pending.
    Short ('sell'): mirror on the last swing HIGH."""
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy|sell")
    work = list(bars[-lookback:]) if lookback > 0 else list(bars)
    if len(work) < fractal_n * 2 + 2:
        return "none"
    tester = work[-1]
    body = work[:-1]
    highs, lows = fractals(body, n=fractal_n)
    if side == "buy":
        if not lows:
            return "none"
        return _sweep_level(tester, body[lows[-1]].low, side="low") or "none"
    if not highs:
        return "none"
    return _sweep_level(tester, body[highs[-1]].high, side="high") or "none"


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
