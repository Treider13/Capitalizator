"""F0 gate is red: no 30d tape, no kill-switch log, withdraw box unchecked."""

from __future__ import annotations

from capitalizator.ops.gates import FAIL, gate_f0


def test_f0_fails_closed_today() -> None:
    code, payload = gate_f0()
    assert code == FAIL
    assert payload["ok"] is False
    checks = payload["checks"]
    assert checks["G0.5_no_place_order"] is True
    assert checks["G0.1_uptime_30d"] is False
    assert checks["G0.6_kill_switch"] is False
    assert checks["G0.7_withdraw_checked"] is False
    assert checks["trading_mode_off"] is True
