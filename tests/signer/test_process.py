"""SQLite queue: desk writes, signer drains. Off mode does not send."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.signer.process import META_HEARTBEAT, drain_once, serve_loop

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_off_does_not_drain(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.enqueue_intent({"symbol": "BTCUSDT"}, created_ts=NOW.isoformat())
    hits: list[dict] = []
    out = drain_once(knowledge, hits.append, user_mode="off", now=NOW)
    assert out == []
    assert hits == []
    assert knowledge.pending_intents()


def test_demo_sends_and_marks(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.enqueue_intent({"symbol": "BTCUSDT", "side": "buy"}, created_ts=NOW.isoformat())

    def send(payload: dict) -> dict:
        return {"status": "sent", "symbol": payload["symbol"]}

    out = drain_once(knowledge, send, user_mode="demo", now=NOW)
    assert out[0]["status"] == "sent"
    assert knowledge.pending_intents() == []


def test_serve_loop_writes_heartbeat(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    n = {"i": 0}

    serve_loop(
        knowledge=knowledge,
        vault=vault,
        send=lambda row: {"status": "not_sent"},
        cancel_all=lambda: None,
        should_stop=lambda: n.update(i=n["i"] + 1) or n["i"] >= 2,
        idle_s=0,
        now=NOW,
    )
    assert knowledge.meta(META_HEARTBEAT) == NOW.isoformat()
