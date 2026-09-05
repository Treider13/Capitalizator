"""Ladder cuts size. It never raises risk above min(step, phase, base)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.hyexec.sizing import STEP_APLUS, STEP_PROBE, STEP_STD, effective_risk


def test_probe_std_aplus_are_the_three_steps() -> None:
    assert STEP_PROBE == Decimal("0.004")
    assert STEP_STD == Decimal("0.01")
    assert STEP_APLUS == Decimal("0.02")


def test_phase_one_percent_caps_aplus() -> None:
    got = effective_risk(
        step="aplus",
        phase_target=Decimal("0.01"),
        base_risk=Decimal("0.02"),
        day_pnl=Decimal("0"),
        window="overlap",
    )
    assert got == Decimal("0.01")


def test_aplus_two_percent_when_phase_allows() -> None:
    got = effective_risk(
        step="aplus",
        phase_target=Decimal("0.02"),
        base_risk=Decimal("0.02"),
        day_pnl=Decimal("0"),
        window="overlap",
    )
    assert got == Decimal("0.02")


def test_model_cannot_raise_above_phase() -> None:
    got = effective_risk(
        step="aplus",
        phase_target=Decimal("0.01"),
        base_risk=Decimal("0.99"),
        day_pnl=Decimal("0"),
        window="overlap",
    )
    assert got <= Decimal("0.01")


def test_aplus_blocked_after_day_minus_one_point_five() -> None:
    got = effective_risk(
        step="aplus",
        phase_target=Decimal("0.02"),
        base_risk=Decimal("0.02"),
        day_pnl=Decimal("-0.015"),
        window="overlap",
    )
    assert got == STEP_STD


def test_aplus_outside_overlap_is_std() -> None:
    got = effective_risk(
        step="aplus",
        phase_target=Decimal("0.02"),
        base_risk=Decimal("0.02"),
        day_pnl=Decimal("0"),
        window="asia",
    )
    assert got == STEP_STD


def test_probe_stays_probe() -> None:
    got = effective_risk(
        step="probe",
        phase_target=Decimal("0.02"),
        base_risk=Decimal("0.02"),
        day_pnl=Decimal("0"),
        window="overlap",
    )
    assert got == STEP_PROBE


def test_unknown_step_raises() -> None:
    with pytest.raises(ValueError, match="step"):
        effective_risk(
            step="hero",
            phase_target=Decimal("0.01"),
            base_risk=Decimal("0.02"),
            day_pnl=Decimal("0"),
            window="overlap",
        )


def test_one_aplus_path_can_print_five_percent() -> None:
    """2% risk × (0.3·1R + 0.7·3R) = 2.4R → +4.8% equity. Not a market promise."""
    risk = Decimal("0.02")
    realized_r = Decimal("0.30") * Decimal("1") + Decimal("0.70") * Decimal("3")
    assert risk * realized_r == Decimal("0.048")
