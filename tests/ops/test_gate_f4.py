"""F4 gate is red: empty micro ≠ 100 live AND 8 weeks."""

from __future__ import annotations

import json
from pathlib import Path

from capitalizator.ops.gates import FAIL, _weeks_spanned, gate_f4


def test_f4_fails_closed_today() -> None:
    code, payload = gate_f4()
    assert code == FAIL
    assert payload["ok"] is False
    assert payload["n_live"] == 0
    assert payload["weeks_spanned"] is None
    assert payload["wr"] is None
    assert payload["gate_time"] is False
    checks = payload["checks"]
    assert checks["G4.1_n100"] is False
    assert checks["G4.2_weeks8"] is False
    assert checks["G4.3_and_not_or"] is True
    assert checks["G4.4_wr"] is False
    assert checks["G4.5_overlay"] is False
    assert checks["G4.6_liq0"] is False
    assert checks["G4.7_against_btc"] is False
    assert checks["G4.8_no_average"] is True
    assert checks["G4_trading_not_live"] is True
    assert checks["G4_equity_not_main"] is True


def test_80_in_three_weeks_is_not_gate_time(tmp_path: Path) -> None:
    dest = tmp_path / "ops" / "gates"
    dest.mkdir(parents=True)
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "gates.yaml").write_text(
        (Path(__file__).resolve().parents[2] / "infra" / "gates.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (tmp_path / "infra" / "phase.yaml").write_text(
        'phase: 0\nbreakout_enabled: false\ntrading_mode: "off"\nequity_source: "none"\n'
        "target_risk: 0.01\nmax_lev: 3\nrequire_human_ack_to_advance: true\n",
        encoding="utf-8",
    )
    rows = [
        {
            "mode": "micro",
            "status": "closed",
            "fill_qty": 1,
            "r": 0.2,
            "opened_at": "2026-09-01T14:00:00Z" if i == 0 else "2026-09-15T14:00:00Z",
        }
        for i in range(80)
    ]
    (dest / "f4_episodes.json").write_text(json.dumps(rows), encoding="utf-8")
    _code, payload = gate_f4(root=tmp_path)
    assert payload["n_live"] == 80
    assert payload["weeks_spanned"] == 3
    assert payload["gate_time"] is False
    assert payload["checks"]["G4.1_n100"] is False
    assert payload["checks"]["G4.2_weeks8"] is False


def test_40_in_eight_weeks_is_not_gate_time() -> None:
    rows = [
        {"opened_at": "2026-09-01T14:00:00Z"},
        {"opened_at": "2026-10-20T14:00:00Z"},
    ]
    assert _weeks_spanned(rows) == 8
    assert _weeks_spanned([]) is None


def test_gate_sql_exists() -> None:
    path = Path(__file__).resolve().parents[2] / "ops" / "gate_f4.sql"
    text = path.read_text(encoding="utf-8")
    assert "mode = 'micro'" in text
    assert "date_diff('week'" in text
