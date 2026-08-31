"""gates.yaml is the PHASE-BUILD table. Extra keys are not silent knobs."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.ops.thresholds import GatesYamlError, load_gates


def test_repo_yaml_has_phase_build_numbers() -> None:
    th = load_gates()
    assert th["f1"]["n_bounce_demo_min"] == 80
    assert th["f3"]["n_break_demo_min"] == 40
    assert th["f3"]["n_sum_demo_min"] == 100
    assert th["f3"]["bounce_slack_r"] == 0.15
    assert th["f3"]["failed_break_in_counts"] is False
    assert th["f4"]["n_live_min"] == 100
    assert th["f4"]["weeks_min"] == 8
    assert th["f5"]["target_risk"] == 0.012


def test_extra_key_is_rejected(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parents[2] / "infra" / "gates.yaml"
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "gates.yaml").write_text(
        src.read_text(encoding="utf-8") + "tune_after_run: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(GatesYamlError, match="unknown"):
        load_gates(root=tmp_path)
