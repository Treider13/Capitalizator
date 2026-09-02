"""Night contour: report + overlay + pending card. No LLM verdict."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.night import run_night
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def test_night_cli_writes_report(tmp_path: Path) -> None:
    from capitalizator.ops.night import main
    from capitalizator.ops.knowledge import open_knowledge as open_k

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
