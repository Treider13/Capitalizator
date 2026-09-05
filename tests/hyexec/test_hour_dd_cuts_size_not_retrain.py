"""Hour drawdown >3% cuts size. It does not retrain on a timer."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.hyexec.adwin import after_hour_dd, should_retrain, timer_retrain


def test_hour_dd_three_percent_halves_risk() -> None:
    got = after_hour_dd(hour_dd=Decimal("-0.03"), risk=Decimal("0.01"))
    assert got == Decimal("0.005")


def test_hour_dd_two_percent_does_not_cut() -> None:
    assert after_hour_dd(hour_dd=Decimal("-0.02"), risk=Decimal("0.01")) == Decimal("0.01")


def test_hour_dd_never_raises() -> None:
    assert after_hour_dd(hour_dd=Decimal("0.10"), risk=Decimal("0.01")) == Decimal("0.01")


def test_timer_does_not_retrain() -> None:
    assert timer_retrain(hours=24) is False
    assert timer_retrain(hours=0) is False


def test_only_adwin_flag_retrains() -> None:
    assert should_retrain(adwin_drift=False) is False
    assert should_retrain(adwin_drift=True) is True
