"""Night contour: facts of the day only — report, overlay, calibration, exam, ОКО/intel state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.night import run_night
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def test_night_cli_writes_report(tmp_path: Path) -> None:
    from capitalizator.ops.knowledge import open_knowledge as open_k
    from capitalizator.ops.night import main

    vault = init_vault(tmp_path / "desk")
    assert main(["--userdir", str(vault.root), "--day", "2026-08-31"]) == 0
    knowledge = open_k(vault)
    try:
        assert knowledge.report(day="2026-08-31", kind="map")
        assert knowledge.get_overlay("2026-08-31:shadow") is not None
        assert knowledge.meta("exam_night") and knowledge.meta("oko_night")
    finally:
        knowledge.close()


def test_night_records_facts_and_never_promotes(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    assert out["n_shadow"] == 0 and out["r_shadow"] is None
    assert out["exam_passed"] is False and out["classes"] == 0
    assert "card" not in out and "fragility" not in out and "replayed" not in out  # placeholders gone
    exam = json.loads(knowledge.meta("exam_night"))
    assert exam["passed"] is False and exam["challenger"]["n"] == 0
    assert knowledge.meta("champion") is None  # the night never flips the champion
    oko = json.loads(knowledge.meta("oko_night"))
    assert oko["passports"] == {} and oko["mirror"] is None
    knowledge.close()


def test_night_scores_journal_shadow_r(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_journal_touch(
        "t1",
        {
            "touch_ts": "2026-08-31T14:10:00+00:00",
            "shadow_would": True,
            "shadow_tag": "bounce",
            "outcome": "bounce",
        },
    )
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    assert out["n_shadow"] == 1
    assert out["r_shadow"] == "1"
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    knowledge.close()
