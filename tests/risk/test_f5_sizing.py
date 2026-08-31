"""5.23 — F5 1.2% only after G4 and equity_source=main. F1 stays 1%."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

from capitalizator.ops.phase import equity_source
from capitalizator.ops.thresholds import load_gates
from capitalizator.risk.f5 import F1_TARGET, F5_TARGET, active_target, f5_target

PHASE = Path(__file__).resolve().parents[2] / "infra" / "phase.yaml"


def test_current_phase_is_not_f5() -> None:
    assert equity_source() == "none"
    assert f5_target(equity_source="none", gate_f4=False) is None
    assert f5_target(equity_source=equity_source(), gate_f4=False) is None
    assert active_target(equity_source=equity_source(), gate_f4=False) == F1_TARGET
    raw = yaml.safe_load(PHASE.read_text(encoding="utf-8"))
    assert raw["target_risk"] == 0.01
    assert raw["equity_source"] == "none"


def test_f5_only_after_g4_and_main() -> None:
    assert f5_target(equity_source="main", gate_f4=True) == F5_TARGET
    assert F5_TARGET == Decimal("0.012")
    assert f5_target(equity_source="main", gate_f4=False) is None
    assert f5_target(equity_source="micro_subaccount", gate_f4=True) is None
    assert f5_target(equity_source="demo", gate_f4=True) is None
    assert active_target(equity_source="main", gate_f4=True) == Decimal("0.012")


def test_yaml_cap_matches_module() -> None:
    th = load_gates()
    assert float(th["f5"]["target_risk"]) == float(F5_TARGET)
    assert float(th["f5"]["target_risk_max_until_written_otherwise"]) == 0.012


def test_f5_does_not_write_phase() -> None:
    before = PHASE.read_text(encoding="utf-8")
    f5_target(equity_source="main", gate_f4=True)
    active_target(equity_source="main", gate_f4=True)
    assert PHASE.read_text(encoding="utf-8") == before
