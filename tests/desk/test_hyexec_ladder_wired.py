"""Desk sizes from the hyexec ladder. Asia scratch does not raise A+."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.sizing import STEP_APLUS, STEP_PROBE, STEP_STD
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.schema import Intent

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


def test_reloaded_day_loss_still_kills_aplus(tmp_path: Path) -> None:
    """WindowHalt must inherit Halts.day_start. Current equity as start hides −2%."""
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    desk = DeskLoop(knowledge=kn, user_mode="off")
    start = desk.account.equity
    desk.account.set_equity(start * Decimal("0.98"), source=desk.account.equity_source, now=NOW)
    desk.account.persist()
    kn.close()
    again = DeskLoop(knowledge=open_knowledge(vault), user_mode="off")
    assert again.account.halts.day_start == start
    assert again.account.equity == start * Decimal("0.98")
    assert again.window_halt.start == again.account.halts.day_start
    assert again.window_halt.day_pnl() == Decimal("-0.02")
    assert again.window_halt.allow_aplus("overlap") is False


def test_new_moscow_day_rebases_window_halt(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    start = desk.account.equity
    desk.tick(NOW)
    desk.window_halt.note_window("asia", start * Decimal("0.98"))
    assert desk.window_halt.allow_aplus("overlap") is False
    nxt = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)  # next Moscow calendar day
    desk.tick(nxt)
    assert desk.account.halts.day_start == desk.account.equity
    assert desk.window_halt.start == desk.account.halts.day_start
    assert desk.window_halt.day_pnl() == Decimal("0")
    assert desk.window_halt.allow_aplus("overlap") is True


def test_hour_dd_three_percent_halves_desk_risk(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    start = desk.account.equity
    desk.tick(NOW)
    desk.account.set_equity(start * Decimal("0.97"), source=desk.account.equity_source, now=NOW)
    assert desk.effective_target_risk() == Decimal("0.005")


def test_hour_dd_two_percent_does_not_cut(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    start = desk.account.equity
    desk.tick(NOW)
    desk.account.set_equity(start * Decimal("0.98"), source=desk.account.equity_source, now=NOW)
    assert desk.effective_target_risk() == desk.risk_config.target_risk_pct


def test_new_hour_rebases_hour_dd(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    start = desk.account.equity
    desk.tick(NOW)
    desk.account.set_equity(start * Decimal("0.97"), source=desk.account.equity_source, now=NOW)
    assert desk.effective_target_risk() == Decimal("0.005")
    nxt = NOW.replace(hour=15)
    desk.tick(nxt)
    assert desk.effective_target_risk() == desk.risk_config.target_risk_pct


def test_compound_uses_live_equity_not_day_start(tmp_path: Path) -> None:
    """Risk % is of today's equity. Doubling the book must double qty."""
    desk = _desk(tmp_path)
    start = desk.account.equity
    intent = Intent(
        symbol="BTCUSDT",
        side="buy",
        entry=Decimal("100"),
        stop=Decimal("98"),
        tp=Decimal("104"),
        tag="bounce",
    )
    first, info1 = desk._size_and_gate(intent, "BTCUSDT", NOW, labels={"window": "overlap"})
    assert first is not None, info1
    desk.account.set_equity(start * 2, source=desk.account.equity_source, now=NOW)
    assert desk.account.sizing_equity() == start * 2
    assert desk.window_halt.start == start
    second, info2 = desk._size_and_gate(intent, "BTCUSDT", NOW, labels={"window": "overlap"})
    assert second is not None, info2
    assert second.qty == first.qty * 2


def test_reloaded_hour_loss_still_halves(tmp_path: Path) -> None:
    """Hour start must survive persist+reload. Current equity as start hides −3%."""
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    desk = DeskLoop(knowledge=kn, user_mode="off")
    start = desk.account.equity
    desk.tick(NOW)
    desk.account.set_equity(start * Decimal("0.97"), source=desk.account.equity_source, now=NOW)
    kn.close()
    again = DeskLoop(knowledge=open_knowledge(vault), user_mode="off")
    again.tick(NOW + timedelta(minutes=10))
    assert again.account.equity == start * Decimal("0.97")
    assert again.effective_target_risk() == Decimal("0.005")
