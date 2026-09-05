"""FLOOR takes half at 1R. EXPAND takes 30% and leaves the body. No profit cap."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.hyexec.expand import EXPAND_TAKE, FLOOR_TAKE, expand_ok, take_at_1r


def test_floor_takes_half() -> None:
    assert take_at_1r(expand=False) == FLOOR_TAKE == Decimal("0.50")


def test_expand_takes_thirty() -> None:
    assert take_at_1r(expand=True) == EXPAND_TAKE == Decimal("0.30")


def test_expand_needs_profit_book_and_overlap() -> None:
    assert (
        expand_ok(
            in_profit=True,
            book_plus=True,
            structure_ok=True,
            window="overlap",
            day_pnl=Decimal("0.03"),
        )
        is True
    )
    assert (
        expand_ok(
            in_profit=False,
            book_plus=True,
            structure_ok=True,
            window="overlap",
            day_pnl=Decimal("0.03"),
        )
        is False
    )
    assert (
        expand_ok(
            in_profit=True,
            book_plus=False,
            structure_ok=False,
            window="overlap",
            day_pnl=Decimal("0.03"),
        )
        is False
    )
    assert (
        expand_ok(
            in_profit=True,
            book_plus=True,
            structure_ok=True,
            window="asia",
            day_pnl=Decimal("0.03"),
        )
        is False
    )


def test_expand_has_no_r_cap() -> None:
    from capitalizator.hyexec import expand as mod

    assert not hasattr(mod, "R_CAP")
    assert getattr(mod, "lock_day_at_pct", None) is None
