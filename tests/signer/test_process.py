"""SQLite queue: desk writes, signer drains. Off mode does not send."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.signer.process import drain_once

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
