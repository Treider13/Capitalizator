"""Gamma exposure label for contour B. No live Deribit call.

SpotGamma 1% dollar-gamma (FlashAlpha-lab / gex-explained):
  GEX_i = gamma * OI * multiplier * spot^2 * 0.01 * sign
  sign = +1 call, -1 put
Without a chain the label is None and context_ok skips GEX.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from capitalizator.card.params import GEX_THRESHOLD

ONE_PCT = Decimal("0.01")


@dataclass(frozen=True)
class OptionRow:
    strike: Decimal
    oi: Decimal
    gamma: Decimal
    right: Literal["C", "P"]
    multiplier: Decimal = Decimal("1")


def gex_bg(
    *,
    spot: Decimal | None = None,
    chain: Sequence[OptionRow] | None = None,
) -> str | None:
    """Format SpotGamma GEX, or None when there is no option chain."""
    if spot is None or not chain:
        return None
    total = Decimal("0")
    for row in chain:
        sign = Decimal("1") if row.right == "C" else Decimal("-1")
        total += row.gamma * row.oi * row.multiplier * spot * spot * ONE_PCT * sign
    return format_gex(total)


def format_gex(value: Decimal) -> str:
    sign = "+" if value >= 0 else "-"
    absv = abs(value)
    if absv >= Decimal("1000000"):
        return f"{sign}{(absv / Decimal('1000000')):.1f}M"
    if absv >= Decimal("1000"):
        return f"{sign}{(absv / Decimal('1000')):.1f}K"
    return f"{sign}{absv:.0f}"


def parse_gex(text: str) -> Decimal | None:
    raw = text.strip().upper().replace(",", "").replace(" ", "")
    if not raw:
        return None
    sign = Decimal("-1") if raw.startswith("-") else Decimal("1")
    body = raw.lstrip("+-")
    mult = Decimal("1")
    if body.endswith("M"):
        mult = Decimal("1000000")
        body = body[:-1]
    elif body.endswith("K"):
        mult = Decimal("1000")
        body = body[:-1]
    try:
        return sign * Decimal(body) * mult
    except Exception:
        return None


def gex_is_green(text: str | None) -> bool | None:
    """None → optional (skip). Else green only when GEX > 1M."""
    if text is None or not str(text).strip():
        return None
    value = parse_gex(str(text))
    if value is None:
        return None
    return value > GEX_THRESHOLD
