"""Fair Value Gap label for contour B. Not an A entry engine.

The gap itself comes from `exec/fvg_mark.latest_fvg` — one implementation for the
journal mark and the card (the card used to accept non-consecutive bars).
Filled when the current price sits inside the gap band (FVG_FILL_FRAC of it).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.card.live import FvgStatus
from capitalizator.card.params import FVG_FILL_FRAC
from capitalizator.exec.fvg_mark import latest_fvg
from capitalizator.zones.model import Bar

__all__ = ["fvg_status", "latest_fvg"]


def fvg_status(bars: Sequence[Bar], *, price: Decimal | None = None) -> FvgStatus:
    gap = latest_fvg(bars)
    if gap is None:
        return "none"
    lo, hi = gap
    px = price if price is not None else bars[-1].close
    width = hi - lo
    if width <= 0:
        return "none"
    # 100% fill: the whole gap band must contain price.
    # 80% would shrink the band by (1 - FVG_FILL_FRAC) from each edge.
    pad = width * (Decimal("1") - FVG_FILL_FRAC) / 2
    if lo + pad <= px <= hi - pad:
        return "filled"
    return "open"
