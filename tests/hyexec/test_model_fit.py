"""Labeled shadow R trains a real booster. Serve scores it. No invented fills."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.hyexec.model import MODEL_NAME, model_path
from capitalizator.hyexec.serve import tick
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault

WHEN = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _labeled(i: int, r: str) -> dict[str, object]:
    row: dict[str, object] = {key: str(i + 1) for key in FEATURE_KEYS}
    row["paper"] = {"shadow": {"filled": True, "r_net": r}}
    row["hyexec_as_of"] = f"2026-09-01T10:00:{i:02d}+00:00"
    return row


def test_train_fits_fifteen_labeled_and_serve_scores(tmp_path: Path) -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("river")
    from capitalizator.hyexec.train import main

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        for i in range(15):
            knowledge.put_journal_touch(f"t{i}", _labeled(i, "1.5"))
    finally:
        knowledge.close()
    assert main(["--userdir", str(vault.root)]) == 0
    assert model_path(vault).is_file()
    assert model_path(vault).name == MODEL_NAME
    knowledge = open_knowledge(vault)
    try:
        body = tick(knowledge, now=WHEN, vault=vault)
    finally:
        knowledge.close()
    assert body["model"] is True
    assert body["fit"] is True
    assert body["n_labeled"] == 15
    assert body["score"] is not None
    assert body["model_go"] is True
    stored = json.loads(open_knowledge(vault).meta("hyexec_serve") or "{}")
    assert stored["model_go"] is True


def test_train_negative_labels_make_serve_hold(tmp_path: Path) -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("river")
    from capitalizator.hyexec.train import main

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        for i in range(15):
            knowledge.put_journal_touch(f"t{i}", _labeled(i, "-1.0"))
    finally:
        knowledge.close()
    assert main(["--userdir", str(vault.root)]) == 0
    knowledge = open_knowledge(vault)
    try:
        body = tick(knowledge, now=WHEN, vault=vault)
    finally:
        knowledge.close()
    assert body["model_go"] is False
    assert body["score"] is not None
    assert body["score"] <= 0
