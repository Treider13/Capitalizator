"""Train opens the vault journal. n<15 or holes → no fit. No invented label."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capitalizator.hyexec.dataset import FEATURE_KEYS, can_fit, complete_n, plan_from_rows
from capitalizator.hyexec.train import plan_from_userdir, tick
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent


def _full_row() -> dict[str, str]:
    return {key: "1" for key in FEATURE_KEYS}


def test_plan_needs_fifteen_labeled_rows() -> None:
    assert plan_from_rows([_full_row() for _ in range(14)])["fit"] is False
    ready = plan_from_rows([_full_row() for _ in range(15)])
    assert ready["n"] == 15
    assert ready["n_labeled"] == 0
    assert ready["fit"] is False
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
    assert main(["--userdir", str(vault.root), "--once"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fit"] is False
    assert out["n"] == 15
    assert out["n_labeled"] == 0
    assert called == []


def test_tick_fills_hx_holes_before_plan(tmp_path: Path) -> None:
    pytest.importorskip("river")
    as_of = datetime(2026, 9, 1, 10, 5, tzinfo=UTC)
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    hole = {key: None for key in FEATURE_KEYS}
    hole["touch_id"] = "t1"
    hole["symbol"] = "BTCUSDT"
    hole["touch_ts"] = as_of.isoformat()
    hole["paper"] = {"shadow": {"filled": True, "r_net": "1.5"}}
    try:
        knowledge.put_journal_touch("t1", hole)
        for i in range(3):
            ts = as_of - timedelta(minutes=2 - i)
            ParquetSink(vault.tape).write(
                MarketEvent(
                    stream="trades",
                    exchange="bybit",
                    symbol="BTCUSDT",
                    exchange_ts=ts,
                    recv_ts=ts,
                    payload={"px": str(100 + i), "qty": "1", "side": "buy"},
                )
            )
        plan = tick(vault, knowledge)
        row = knowledge.journal_rows()[0]
    finally:
        knowledge.close()
    assert plan["filled"] >= 1
    assert plan["fit"] is False
    assert row["paper"]["shadow"]["r_net"] == "1.5"
    assert any(row.get(k) not in {None, "", "null", "none"} for k in FEATURE_KEYS)


def test_tick_does_not_rewalk_the_same_holes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("river")
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    hole = {key: None for key in FEATURE_KEYS}
    hole["touch_id"] = "t1"
    hole["symbol"] = "BTCUSDT"
    hole["touch_ts"] = datetime(2026, 9, 1, 10, 5, tzinfo=UTC).isoformat()
    calls: list[int] = []

    def fake_load(*_a, **_k):
        calls.append(1)
        return []

    monkeypatch.setattr(
        "capitalizator.hyexec.tape_day.load_trade_events", fake_load
    )
    try:
        knowledge.put_journal_touch("t1", hole)
        tick(vault, knowledge)
        tick(vault, knowledge)
    finally:
        knowledge.close()
    assert calls == [1]
