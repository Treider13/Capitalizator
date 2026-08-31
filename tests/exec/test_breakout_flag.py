"""3.13.1 — breakout stays off until gate F2. No BreakoutStrategy is called."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from capitalizator.ops.phase import as_breakout_flag, breakout_enabled

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "capitalizator"


def test_phase_breakout_is_false_bool() -> None:
    raw = yaml.safe_load((ROOT / "infra" / "phase.yaml").read_text(encoding="utf-8"))
    assert raw["breakout_enabled"] is False
    assert isinstance(raw["breakout_enabled"], bool)
    assert breakout_enabled() is False


def test_string_false_is_not_a_bool() -> None:
    raw = yaml.safe_load('breakout_enabled: "false"')
    assert raw["breakout_enabled"] == "false"
    with pytest.raises(ValueError, match="bool"):
        as_breakout_flag(raw["breakout_enabled"])


def test_no_breakout_strategy_class() -> None:
    hits = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "class BreakoutStrategy" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_bounce_does_not_import_breakout() -> None:
    text = (SRC / "exec" / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "Breakout" not in text
    assert "breakout_enabled" not in text
    assert "FirstMinute" not in text
