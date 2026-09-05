"""Train opens the vault journal. n<15 or holes → no fit. No invented label."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from capitalizator.hyexec.dataset import FEATURE_KEYS, can_fit, complete_n, plan_from_rows
from capitalizator.hyexec.train import plan_from_userdir
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def _full_row() -> dict[str, str]:
    return {key: "1" for key in FEATURE_KEYS}


def test_plan_needs_fifteen_complete_rows() -> None:
    assert plan_from_rows([_full_row() for _ in range(14)])["fit"] is False
    ready = plan_from_rows([_full_row() for _ in range(15)])
    assert ready["n"] == 15
    assert ready["fit"] is True
    holes = [{key: None for key in FEATURE_KEYS} for _ in range(15)]
    assert plan_from_rows(holes)["fit"] is False
    assert complete_n(holes) == 0


def test_plan_from_userdir_reads_journal(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        for i in range(3):
            knowledge.put_journal_touch(f"t{i}", _full_row())
        knowledge.put_journal_touch("hole", {key: None for key in FEATURE_KEYS})
    finally:
        knowledge.close()
    plan = plan_from_userdir(vault.root)
    assert plan["n"] == 3
    assert plan["n_rows"] == 4
    assert plan["fit"] is False
    assert can_fit(plan["n"]) is False


def test_cli_opens_vault_and_does_not_call_xgboost_train(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("river")
    import xgboost

    from capitalizator.hyexec.train import main

    called: list[object] = []
    monkeypatch.setattr(xgboost, "train", lambda *a, **k: called.append(True))
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        for i in range(15):
            knowledge.put_journal_touch(f"t{i}", _full_row())
    finally:
        knowledge.close()
    assert main(["--userdir", str(vault.root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fit"] is True
    assert out["n"] == 15
    assert called == []
