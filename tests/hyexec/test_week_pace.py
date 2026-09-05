"""Month floor is 30%. A week behind pace is a door bug, not a smaller target."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.hyexec.pace import MONTH_FLOOR, WEEK_PACE, behind_floor, week_target


def test_floor_and_week_constants() -> None:
    assert MONTH_FLOOR == Decimal("0.30")
    assert WEEK_PACE == Decimal("0.075")
    assert week_target() == WEEK_PACE


def test_ten_percent_by_day_fifteen_is_behind() -> None:
    assert behind_floor(month_pnl=Decimal("0.10"), elapsed_days=15) is True


def test_thirty_percent_by_day_twenty_two_is_on_pace() -> None:
    assert behind_floor(month_pnl=Decimal("0.30"), elapsed_days=22) is False


def test_zero_days_is_not_behind() -> None:
    assert behind_floor(month_pnl=Decimal("0"), elapsed_days=0) is False


def test_pyramid_off_when_week_below_pace() -> None:
    from capitalizator.hyexec.pace import pyramid_ok

    assert pyramid_ok(week_pnl=Decimal("0.074")) is False
    assert pyramid_ok(week_pnl=Decimal("0.075")) is True
    assert pyramid_ok(week_pnl=Decimal("-0.01")) is False
