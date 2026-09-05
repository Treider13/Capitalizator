"""Risk ladder. Never raises above min(step, phase.target, base_risk)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from capitalizator.card.first_fact import PROBE_SIZE

STEP_PROBE = Decimal("0.004")
STEP_STD = Decimal("0.01")
STEP_APLUS = Decimal("0.02")
APLUS_DAY_CUT = Decimal("-0.015")
STEPS = frozenset({"probe", "std", "aplus"})
Step = Literal["probe", "std", "aplus"]


def desk_step(
    *,
    first_fact_tag: str,
    size_mult: Decimal,
    aplus: bool,
    window: str,
    day_pnl: Decimal,
) -> str:
    """Pick the ladder step. A probe cut already on the ticket is not stacked."""
    if first_fact_tag == "shadow_gesture":
        raise ValueError("shadow has no step")
    if first_fact_tag == "probe_gesture":
        if size_mult <= PROBE_SIZE:
            return "std"
        return "probe"
    if aplus and window == "overlap" and day_pnl > APLUS_DAY_CUT:
        return "aplus"
    return "std"


def effective_risk(
    *,
    step: str,
    phase_target: Decimal,
    base_risk: Decimal,
    day_pnl: Decimal,
    window: str,
) -> Decimal:
    if step not in STEPS:
        raise ValueError(f"unknown step: {step!r}")
    if phase_target <= 0 or base_risk <= 0:
        raise ValueError("phase_target and base_risk must be > 0")
    wanted = {"probe": STEP_PROBE, "std": STEP_STD, "aplus": STEP_APLUS}[step]
    if step == "aplus" and (window != "overlap" or day_pnl <= APLUS_DAY_CUT):
        wanted = STEP_STD
    ceiling = phase_target if phase_target < base_risk else base_risk
    return wanted if wanted < ceiling else ceiling
