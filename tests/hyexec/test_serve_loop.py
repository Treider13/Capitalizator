"""Serve stays up and stamps timing facts. It never invents model_go."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.hyexec.serve import main, serve_loop, tick
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault

WHEN = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def test_tick_stamps_model_go_none(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        knowledge.put_journal_touch("t1", {key: "1" for key in FEATURE_KEYS})
        body = tick(knowledge, now=WHEN)
    finally:
        knowledge.close()
    assert body["model_go"] is None
    assert body["n"] == 1
    assert body["fit"] is False
    raw = open_knowledge(vault).meta("hyexec_serve")
    assert raw is not None
    stored = json.loads(raw)
    assert stored["model_go"] is None
    assert stored["as_of"] == WHEN.isoformat()


def test_serve_loop_one_tick_then_stops(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    ticks = serve_loop(
        userdir=vault.root,
        should_stop=lambda: False,
        idle_s=0,
        now=WHEN,
    )
    assert ticks == 1
    stored = json.loads(open_knowledge(vault).meta("hyexec_serve") or "{}")
    assert stored["model_go"] is None


def test_serve_once_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = init_vault(tmp_path / "desk")
    assert main(["--userdir", str(vault.root), "--once"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model_go"] is None
    assert out["n"] == 0
