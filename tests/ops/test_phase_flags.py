"""PHASE-BUILD flags stay at phase 0 until a gate writes them. We do not.

Bare YAML `off`/`none` are bool/null. Modes must be quoted strings.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from capitalizator.ops.phase import equity_source, trading_mode

PHASE = Path(__file__).resolve().parents[2] / "infra" / "phase.yaml"


def test_phase_file_is_still_f0_off() -> None:
    raw = yaml.safe_load(PHASE.read_text(encoding="utf-8"))
    assert raw["phase"] == 0
    assert raw["trading_mode"] == "off"
    assert isinstance(raw["trading_mode"], str)
    assert raw["equity_source"] == "none"
    assert isinstance(raw["equity_source"], str)
    assert raw["breakout_enabled"] is False
    assert raw["target_risk"] == 0.01
    assert raw["max_lev"] == 3
    assert raw["require_human_ack_to_advance"] is True
    assert trading_mode() == "off"
    assert equity_source() == "none"


def test_bare_yaml_off_is_not_the_mode_name() -> None:
    """Document the footgun: unquoted off becomes False."""
    assert yaml.safe_load("trading_mode: off")["trading_mode"] is False
    assert yaml.safe_load('trading_mode: "off"')["trading_mode"] == "off"
