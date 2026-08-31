"""F1 gate is red: zero closed demo bounces. Does not invent 80 fills."""

from __future__ import annotations

from pathlib import Path

from capitalizator.ops.gates import FAIL, _f1_closed_bounce, gate_f1


def test_f1_fails_closed_today() -> None:
    code, payload = gate_f1()
    assert code == FAIL
    assert payload["ok"] is False
    assert payload["n_bounce"] == 0
    assert payload["avg_r"] is None
    checks = payload["checks"]
    assert checks["G1.1_n80"] is False
    assert checks["G1.2_avg_r_pos"] is False
    assert checks["G1.3_no_average"] is True
    assert checks["G1.4_zlg_no_random"] is True
    assert checks["G1.5_breakout_off"] is True


def test_junk_rows_are_not_closed_bounces() -> None:
    assert _f1_closed_bounce({}) is False
    assert _f1_closed_bounce({"mode": "demo", "setup_tag": "bounce"}) is False
    assert (
        _f1_closed_bounce(
            {
                "mode": "demo",
                "setup_tag": "bounce",
                "status": "closed",
                "fill_qty": 1,
                "r": 0.4,
            }
        )
        is True
    )


def test_gate_sql_exists() -> None:
    path = Path(__file__).resolve().parents[2] / "ops" / "gate_f1.sql"
    text = path.read_text(encoding="utf-8")
    assert "mode = 'demo'" in text
    assert "setup_tag = 'bounce'" in text
    assert "average_in" in text
