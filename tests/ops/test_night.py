"""Night contour: report + overlay + pending card. No LLM verdict."""

from __future__ import annotations

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
    finally:
        knowledge.close()


def test_night_writes_report_and_pending_card(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    out = run_night(knowledge, day="2026-08-31", now=NOW, thin_book=True)
    assert out["verdict"] == "pending"
    assert out["card"].claims[0].verdict == "pending"
    assert len(out["card"].claims) == 5
    assert knowledge.report(day="2026-08-31", kind="map")
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] is None
    assert out["fragility"] is False
    assert out["n_shadow"] == 0
    assert out["r_shadow"] is None


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
    assert overlay["r_shadow"] == "1"
