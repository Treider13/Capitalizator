"""Month floor +30%. Behind pace means fix doors, not shrink the floor."""

from __future__ import annotations

from decimal import Decimal

MONTH_FLOOR = Decimal("0.30")
WEEK_PACE = Decimal("0.075")
TRADING_DAYS = 22


def week_target() -> Decimal:
    return WEEK_PACE


def pyramid_ok(*, week_pnl: Decimal) -> bool:
    """Second leg only after the week has already made the pace. Catch-up is death."""
    return week_pnl >= WEEK_PACE


def behind_floor(
    *,
    month_pnl: Decimal,
    elapsed_days: int,
    trading_days: int = TRADING_DAYS,
) -> bool:
    if elapsed_days <= 0:
        return False
    if trading_days <= 0:
        raise ValueError("trading_days must be > 0")
    need = MONTH_FLOOR * (Decimal(elapsed_days) / Decimal(trading_days))
    return month_pnl < need
