"""hyexec.yaml: known keys only. Extra knobs die the same way as registry.yaml."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from capitalizator.hyexec.config import HyexecConfigError, load_hyexec

REPO_YAML = Path(__file__).resolve().parents[2] / "infra" / "hyexec.yaml"


def test_unknown_key_is_error(tmp_path: Path) -> None:
    path = tmp_path / "hyexec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "identifier": "hx-test",
                "gate_mode": "size_timing",
                "probe_risk": "0.004",
                "std_risk": "0.01",
                "aplus_risk": "0.02",
                "invented_knob": "no",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(HyexecConfigError, match="unknown keys"):
        load_hyexec(path)


def test_triple_and_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hyexec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "identifier": "hx-test",
                "gate_mode": "triple_and",
                "probe_risk": "0.004",
                "std_risk": "0.01",
                "aplus_risk": "0.02",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(HyexecConfigError, match="size_timing"):
        load_hyexec(path)


def test_aplus_cannot_exceed_two_percent(tmp_path: Path) -> None:
    path = tmp_path / "hyexec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "identifier": "hx-test",
                "gate_mode": "size_timing",
                "probe_risk": "0.004",
                "std_risk": "0.01",
                "aplus_risk": "0.05",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(HyexecConfigError, match="aplus_risk"):
        load_hyexec(path)


def test_repo_yaml_loads() -> None:
    cfg = load_hyexec(REPO_YAML)
    assert cfg.gate_mode == "size_timing"
    assert cfg.aplus_risk == Decimal("0.02")
