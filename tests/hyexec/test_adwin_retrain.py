"""A second train pass refits only after ADWIN, never because time passed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capitalizator.hyexec.adwin import timer_retrain
from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.hyexec.model import model_path
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def _labeled(i: int, r: str) -> dict[str, object]:
    when = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=i)
    row: dict[str, object] = {key: str((i % 9) + 1) for key in FEATURE_KEYS}
    row["paper"] = {"shadow": {"filled": True, "r_net": r}}
    row["hyexec_as_of"] = when.isoformat()
    return row


def test_timer_still_does_not_retrain() -> None:
    assert timer_retrain(hours=24) is False


def test_second_once_does_not_refit_without_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("river")
    import xgboost

    from capitalizator.hyexec.train import main

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        for i in range(15):
            knowledge.put_journal_touch(f"t{i}", _labeled(i, "1.5"))
    finally:
        knowledge.close()
    assert main(["--userdir", str(vault.root), "--once"]) == 0
    assert model_path(vault).is_file()
    called: list[object] = []
    monkeypatch.setattr(xgboost, "train", lambda *a, **k: called.append(True))
    assert main(["--userdir", str(vault.root), "--once"]) == 0
    assert called == []


def test_mean_shift_after_fit_retrains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("river")
    import xgboost

    from capitalizator.hyexec.train import main

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        for i in range(15):
            knowledge.put_journal_touch(f"t{i}", _labeled(i, "1.5"))
    finally:
        knowledge.close()
    assert main(["--userdir", str(vault.root), "--once"]) == 0
    knowledge = open_knowledge(vault)
    try:
        for i in range(80):
            knowledge.put_journal_touch(f"s{i}", _labeled(15 + i, "1.5"))
        for i in range(80):
            knowledge.put_journal_touch(f"n{i}", _labeled(95 + i, "-1.0"))
    finally:
        knowledge.close()
    called: list[object] = []
    real = xgboost.train

    def _wrap(*a, **k):
        called.append(True)
        return real(*a, **k)

    monkeypatch.setattr(xgboost, "train", _wrap)
    assert main(["--userdir", str(vault.root), "--once"]) == 0
    assert called == [True]
