"""F3 gate is red: no 40 breakouts, empty ≠ clean book."""

from __future__ import annotations

from pathlib import Path

from capitalizator.ops.gates import FAIL, _closed_demo, gate_f3


def test_f3_fails_closed_today() -> None:
    code, payload = gate_f3()
    assert code == FAIL
    assert payload["ok"] is False
    assert payload["n_break"] == 0
    assert payload["n_sum"] == 0
    assert payload["avg_r_sum"] is None
    assert payload["f1_end_avg"] is None
    assert payload["whale_entries"] == 0
    checks = payload["checks"]
    assert checks["G3.1_n40_break"] is False
    assert checks["G3.2_bounce_not_degraded"] is False
    assert checks["G3.3_n100_sum"] is False
    assert checks["G3.4_avg_r_pos"] is False
    assert checks["G3.5_ai_quarantine"] is True
    assert checks["G3.6_no_whale_entry"] is True
    assert checks["G3.7_squeeze"] is False
    assert checks["G3_breakout_off"] is True
    assert checks["G3_no_strategy_breakout"] is True


def test_failed_break_is_not_a_breakout() -> None:
    row = {
        "mode": "demo",
        "setup_tag": "failed_break",
        "status": "closed",
        "fill_qty": 1,
        "r": 0.4,
    }
    assert _closed_demo(row, frozenset({"breakout"})) is False
    assert _closed_demo(row, frozenset({"bounce", "breakout"})) is False


def test_gate_sql_exists() -> None:
    path = Path(__file__).resolve().parents[2] / "ops" / "gate_f3.sql"
    text = path.read_text(encoding="utf-8")
    assert "setup_tag = 'breakout'" in text
    assert "failed_break" in text
    assert "entry_reason = 'whale'" in text
