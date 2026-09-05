"""Desk sizes from the hyexec ladder. Asia scratch does not raise A+."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.sizing import STEP_APLUS, STEP_PROBE, STEP_STD
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "desk")), user_mode="off")


def test_desk_owns_window_halt(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    assert desk.window_halt.start == desk.account.equity
    desk.window_halt.note_window("asia", desk.account.equity * Decimal("0.98"))
    assert desk.window_halt.allow_entry("overlap") is True
    assert desk.window_halt.allow_aplus("overlap") is False


def test_desk_probe_target_is_point_four(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    got = desk.effective_target_risk(step="probe", window="overlap")
    assert got == STEP_PROBE
    assert got < desk.risk_config.target_risk_pct


def test_desk_aplus_outside_overlap_is_std(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    got = desk.effective_target_risk(step="aplus", window="asia")
    assert got == STEP_STD
    assert got < STEP_APLUS


def test_desk_aplus_after_asia_scratch_is_std(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    start = desk.account.equity
    desk.window_halt.note_window("asia", start * Decimal("0.98"))
    got = desk.effective_target_risk(step="aplus", window="overlap")
    assert got == STEP_STD


def test_desk_drift_still_caps_the_ladder(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.drift_active = True
    got = desk.effective_target_risk(step="std", window="overlap")
    assert got == Decimal("0.005")
    assert desk.effective_target_risk(step="aplus", window="overlap") == Decimal("0.005")


def test_desk_no_arg_effective_target_matches_std(tmp_path: Path) -> None:
    """Old callers (drift UI) keep working."""
    desk = _desk(tmp_path)
    assert desk.effective_target_risk() == desk.risk_config.target_risk_pct
