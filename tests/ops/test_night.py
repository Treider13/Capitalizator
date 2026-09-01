"""Night contour: report + overlay + pending card. No LLM verdict."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.night import run_night
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def test_night_writes_report_and_pending_card(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    out = run_night(knowledge, day="2026-08-31", now=NOW)
    assert out["verdict"] == "pending"
    assert out["card"].claims[0].verdict == "pending"
    assert len(out["card"].claims) == 5
    assert knowledge.report(day="2026-08-31", kind="map")
    assert knowledge.get_overlay("2026-08-31:shadow") is not None
    assert out["fragility"] is False
