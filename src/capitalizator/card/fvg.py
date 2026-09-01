"""Fair Value Gap label for contour B. Three-candle gap. Not an A entry engine.

Bullish: High1 < Low3. Bearish: Low1 > High3.
Filled when the current price sits inside the gap (100% fill).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from capitalizator.card.live import FvgStatus
from capitalizator.card.params import FVG_FILL_FRAC
from capitalizator.zones.model import Bar


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


def latest_fvg(bars: Sequence[Bar]) -> tuple[Decimal, Decimal] | None:
    """Most recent three-candle gap (low, high), or None."""
    if len(bars) < 3:
        return None
    found: tuple[Decimal, Decimal] | None = None
    for i in range(2, len(bars)):
        first, _mid, third = bars[i - 2], bars[i - 1], bars[i]
        if first.high < third.low:
            found = (first.high, third.low)
        elif first.low > third.high:
            found = (third.high, first.low)
    return found
