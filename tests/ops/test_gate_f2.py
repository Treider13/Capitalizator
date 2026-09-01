"""F2 gate is red: no 50 cards, no live veto journal. Empty is not a clean book."""

from __future__ import annotations

from capitalizator.ops.gates import FAIL, gate_f2


def test_f2_fails_closed_today() -> None:
    code, payload = gate_f2()
    assert code == FAIL
    assert payload["ok"] is False
    assert payload["n_cards"] == 0
    assert payload["n_veto"] == 0
    assert payload["n_closed"] == 0
    assert payload["parsed_n"] == 0
    checks = payload["checks"]
    assert checks["G2.1_veto_lived"] is False
    assert checks["G2.2_veto_shadow_or_n"] is False
    assert checks["G2.3_against_btc"] is False
    assert checks["G2.4_cards_50"] is False
    assert checks["G2.5_verifier_not_llm"] is True
    assert checks["G2.6_redteam_ci"] is False
    assert checks["G2_breakout_off"] is True
    assert checks["G2_parsed_50"] is False
    assert checks["G2_veto_in_propose"] is True
