"""4.19.2 — drift cuts target to 0.5%. No drift keeps 1%. Does not write phase.yaml."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

from capitalizator.risk.drift_cut import DRIFT_TARGET, target_after_drift

PHASE = Path(__file__).resolve().parents[2] / "infra" / "phase.yaml"


def test_drift_cuts_to_half_percent() -> None:
    assert target_after_drift(drift=True) == DRIFT_TARGET
    assert DRIFT_TARGET == Decimal("0.005")


def test_no_drift_keeps_base() -> None:
    assert target_after_drift(drift=False) == Decimal("0.01")


def test_does_not_raise_risk() -> None:
    assert target_after_drift(drift=True) < Decimal("0.01")


def test_phase_yaml_target_unchanged() -> None:
    raw = yaml.safe_load(PHASE.read_text(encoding="utf-8"))
    assert raw["target_risk"] == 0.01
