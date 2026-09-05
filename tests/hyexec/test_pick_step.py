"""Desk step: probe on the ticket is not also a probe risk fraction."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.card.first_fact import PROBE_SIZE
from capitalizator.hyexec.sizing import STEP_APLUS, STEP_PROBE, STEP_STD, desk_step, effective_risk


def test_probe_size_mult_already_on_ticket_uses_std_step() -> None:
    """Bounce already put 0.40 on the intent. Ladder must not also pick 0.4%."""
    step = desk_step(
        first_fact_tag="probe_gesture",
        size_mult=PROBE_SIZE,
        aplus=False,
        window="overlap",
        day_pnl=Decimal("0"),
    )
    assert step == "std"
    risk = effective_risk(
        step=step,
        phase_target=Decimal("0.01"),
        base_risk=Decimal("0.01"),
        day_pnl=Decimal("0"),
        window="overlap",
    )
    assert risk == STEP_STD
    assert risk * PROBE_SIZE == STEP_PROBE


def test_probe_without_size_cut_uses_probe_step() -> None:
    step = desk_step(
        first_fact_tag="probe_gesture",
        size_mult=Decimal("1"),
        aplus=True,
        window="overlap",
        day_pnl=Decimal("0"),
    )
    assert step == "probe"
    assert (
        effective_risk(
            step=step,
            phase_target=Decimal("0.02"),
            base_risk=Decimal("0.02"),
            day_pnl=Decimal("0"),
            window="overlap",
        )
        == STEP_PROBE
    )


def test_probe_never_upgrades_to_aplus() -> None:
    step = desk_step(
        first_fact_tag="probe_gesture",
        size_mult=PROBE_SIZE,
        aplus=True,
        window="overlap",
        day_pnl=Decimal("0"),
    )
    assert step != "aplus"


def test_mature_aplus_in_overlap_is_aplus() -> None:
    step = desk_step(
        first_fact_tag="first_fact",
        size_mult=Decimal("1"),
        aplus=True,
        window="overlap",
        day_pnl=Decimal("0"),
    )
    assert step == "aplus"
    assert (
        effective_risk(
            step=step,
            phase_target=Decimal("0.02"),
            base_risk=Decimal("0.02"),
            day_pnl=Decimal("0"),
            window="overlap",
        )
        == STEP_APLUS
    )


def test_shadow_has_no_step() -> None:
    import pytest

    with pytest.raises(ValueError, match="shadow"):
        desk_step(
            first_fact_tag="shadow_gesture",
            size_mult=Decimal("1"),
            aplus=False,
            window="overlap",
            day_pnl=Decimal("0"),
        )
