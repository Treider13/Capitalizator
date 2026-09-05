"""FLOOR vs EXPAND take at +1R. No profit cap lives in this module."""

from __future__ import annotations

from decimal import Decimal

FLOOR_TAKE = Decimal("0.50")
EXPAND_TAKE = Decimal("0.30")
lock_day_at_pct = None


def take_at_1r(*, expand: bool) -> Decimal:
    return EXPAND_TAKE if expand else FLOOR_TAKE


def expand_ok(
    *,
    in_profit: bool,
    book_plus: bool,
    structure_ok: bool,
    window: str,
    day_pnl: Decimal,
) -> bool:
    if not in_profit:
        return False
    if not book_plus and not structure_ok:
        return False
    if window != "overlap":
        return False
    if day_pnl < Decimal("0.03"):
        return False
    return True
