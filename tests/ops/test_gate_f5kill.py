"""F5 kill does not invent a −3% day and does not write phase.yaml."""

from __future__ import annotations

from pathlib import Path

from capitalizator.ops.gates import ACCIDENT, FAIL, gate_f5kill

PHASE = Path(__file__).resolve().parents[2] / "infra" / "phase.yaml"


def test_f5kill_fails_without_inventing_pnl() -> None:
    before = PHASE.read_text(encoding="utf-8")
    code, payload = gate_f5kill()
    assert code == FAIL
    assert payload["ok"] is False
    assert payload["writes_phase"] is False
    assert payload["ack"] is False
    checks = payload["checks"]
    assert checks["K5_target_cap"] is True
    assert checks["K5_in_f5"] is False
    assert checks["K5_pnl_known"] is False
    assert PHASE.read_text(encoding="utf-8") == before


def test_target_above_012_is_accident(tmp_path: Path) -> None:
    (tmp_path / "infra").mkdir()
    (tmp_path / "ops" / "gates").mkdir(parents=True)
    (tmp_path / "infra" / "gates.yaml").write_text(
        (Path(__file__).resolve().parents[2] / "infra" / "gates.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (tmp_path / "infra" / "phase.yaml").write_text(
        'phase: 5\nbreakout_enabled: false\ntrading_mode: "off"\nequity_source: "main"\n'
        "target_risk: 0.02\nmax_lev: 3\nrequire_human_ack_to_advance: true\n",
        encoding="utf-8",
    )
    code, payload = gate_f5kill(root=tmp_path)
    assert code == ACCIDENT
    assert payload["checks"]["K5_target_cap"] is False
    assert payload["target_risk"] == 0.02
