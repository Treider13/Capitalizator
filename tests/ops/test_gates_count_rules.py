"""Gate counters: 80/40/100 are thresholds. Fixtures here are not live fills."""

from __future__ import annotations

import json
from pathlib import Path

from capitalizator.ops.gates import FAIL, _closed_demo, _f1_closed_bounce, gate_f1, gate_f3


def _row(*, tag: str = "bounce", r: float = 0.1) -> dict[str, object]:
    return {
        "mode": "demo",
        "setup_tag": tag,
        "status": "closed",
        "fill_qty": 1,
        "r": r,
    }


def test_repo_f1_is_still_zero() -> None:
    code, payload = gate_f1()
    assert code == FAIL
    assert payload["n_bounce"] == 0


def test_failed_break_is_not_a_closed_bounce() -> None:
    assert _f1_closed_bounce(_row(tag="failed_break")) is False
    assert _f1_closed_bounce(_row(tag="breakout")) is False
    assert _f1_closed_bounce(_row(tag="bounce")) is True


def test_79_bounces_do_not_pass_n80(tmp_path: Path) -> None:
    dest = tmp_path / "ops" / "gates"
    dest.mkdir(parents=True)
    (dest / "f1_episodes.json").write_text(
        json.dumps([_row() for _ in range(79)]),
        encoding="utf-8",
    )
    _code, payload = gate_f1(root=tmp_path)
    assert payload["checks"]["G1.1_n80"] is False
    assert payload["n_bounce"] == 79


def test_80_failed_breaks_do_not_count_as_bounces(tmp_path: Path) -> None:
    dest = tmp_path / "ops" / "gates"
    dest.mkdir(parents=True)
    (dest / "f1_episodes.json").write_text(
        json.dumps([_row(tag="failed_break") for _ in range(80)]),
        encoding="utf-8",
    )
    _code, payload = gate_f1(root=tmp_path)
    assert payload["n_bounce"] == 0
    assert payload["checks"]["G1.1_n80"] is False


def test_split_sql_keeps_failed_break_out_of_both() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "ops" / "setup_split.sql").read_text(encoding="utf-8")
    assert "setup_tag = 'bounce'" in text
    assert "setup_tag = 'breakout'" in text
    assert "failed_break" in text
    assert "n = 80" not in text


def _f3_root(tmp_path: Path) -> Path:
    dest = tmp_path / "ops" / "gates"
    dest.mkdir(parents=True)
    exec_dir = tmp_path / "src" / "capitalizator" / "exec"
    exec_dir.mkdir(parents=True)
    (exec_dir / "strategy_bounce.py").write_text("# paper\n", encoding="utf-8")
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "gates.yaml").write_text(
        (Path(__file__).resolve().parents[2] / "infra" / "gates.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_39_breakouts_do_not_pass_n40(tmp_path: Path) -> None:
    root = _f3_root(tmp_path)
    rows = [_row(tag="breakout") for _ in range(39)]
    (root / "ops" / "gates" / "f1_episodes.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    _code, payload = gate_f3(root=root)
    assert payload["n_break"] == 39
    assert payload["checks"]["G3.1_n40_break"] is False
    assert payload["ok"] is False


def test_40_failed_breaks_do_not_count_as_breakouts(tmp_path: Path) -> None:
    root = _f3_root(tmp_path)
    rows = [_row(tag="failed_break") for _ in range(40)]
    (root / "ops" / "gates" / "f1_episodes.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    _code, payload = gate_f3(root=root)
    assert payload["n_break"] == 0
    assert payload["n_sum"] == 0
    assert payload["checks"]["G3.1_n40_break"] is False
    assert _closed_demo(rows[0], frozenset({"breakout"})) is False


def test_100_bounces_without_breakouts_do_not_pass_f3(tmp_path: Path) -> None:
    root = _f3_root(tmp_path)
    rows = [_row(tag="bounce") for _ in range(100)]
    (root / "ops" / "gates" / "f1_episodes.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    _code, payload = gate_f3(root=root)
    assert payload["n_sum"] == 100
    assert payload["n_break"] == 0
    assert payload["checks"]["G3.3_n100_sum"] is True
    assert payload["checks"]["G3.1_n40_break"] is False
    assert payload["ok"] is False
