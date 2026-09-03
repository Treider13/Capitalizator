"""Compute B card labels from closed bars. None when the series is short."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from capitalizator.card.fvg import fvg_status
from capitalizator.card.gex import OptionRow, gex_bg
from capitalizator.card.live import FibZone, FvgStatus, SweepStatus, fib_zone_at
from capitalizator.card.rsi import rsi_htf
from capitalizator.card.smc import bos_status, ob_status
from capitalizator.card.sweep import fractals, sweep_status, sweep_status_for
from capitalizator.zones.model import Bar

_STRUCTURE_TF = ("15m", "1h", "4h", "1d")


@dataclass(frozen=True)
class BLabels:
    rsi_htf: str | None = None
    fvg_status: FvgStatus = "none"
    sweep_status: SweepStatus = "none"
    fib_zone: FibZone = "none"
    fib_level: str | None = None
    ob_status: str | None = None
    bos_status: str | None = None
    gex_bg: str | None = None
    fib_zone_short: FibZone = "none"
    fib_level_short: str | None = None
    # Side-aware sweeps: fuel for a long is the swing LOW taken; for a short the HIGH.
    sweep_long: SweepStatus = "none"
    sweep_short: SweepStatus = "none"


def compute_b_labels(
    bars: Sequence[Bar],
    *,
    price: Decimal | None = None,
    chain: Sequence[OptionRow] | None = None,
    spot: Decimal | None = None,
) -> BLabels:
    if not bars:
        return BLabels()
    structure = _structure_bars(bars)
    px = price if price is not None else structure[-1].close
    fib_zone, fib_level = _fib(structure, px)
    fib_zone_short, fib_level_short = _fib(structure, px, side="sell")
    return BLabels(
        rsi_htf=rsi_htf(bars),
        fvg_status=fvg_status(structure, price=px),
        sweep_status=sweep_status(structure),
        fib_zone=fib_zone,
        fib_level=fib_level,
        ob_status=ob_status(structure),
        bos_status=bos_status(structure),
        gex_bg=gex_bg(spot=spot if spot is not None else px, chain=chain),
        fib_zone_short=fib_zone_short,
        fib_level_short=fib_level_short,
        sweep_long=sweep_status_for(structure, "buy"),
        sweep_short=sweep_status_for(structure, "sell"),
    )


def _structure_bars(bars: Sequence[Bar]) -> list[Bar]:
    for tf in _STRUCTURE_TF:
        subset = [b for b in bars if b.tf == tf]
        if len(subset) >= 5:
            return subset
    return list(bars)


def _fib(
    bars: Sequence[Bar], price: Decimal, *, side: str = "buy"
) -> tuple[FibZone, str | None]:
    """Retrace between the last confirmed swing high and swing low.

    Window min/max on a trend pins the high at the last bar and paints
    forbidden_0_05 forever. A confirmed fractal is already two bars old, so a
    new high is an extension (fib none), not a 0–0.5 pullback.
    """
    highs, lows = fractals(bars)
    if not highs or not lows:
        return "none", None
    high = bars[highs[-1]].high
    low = bars[lows[-1]].low
    if high <= low:
        return "none", None
    zone, level = fib_zone_at(low=low, high=high, price=price, side=side)
    return zone, level
