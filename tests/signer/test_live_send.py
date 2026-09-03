"""user_mode=live drains through validate onto the injected send."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.signer.process import drain_validated

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def _intent() -> dict[str, str]:
    return {
        "symbol": "BTCUSDT",
        "side": "buy",
        "entry": "60000",
        "stop": "59400",
        "tp": "61200",
        "tag": "bounce",
        "size_mult": "1",
    }


def test_live_drain_sends_mainnet_payload(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    seen: list[dict] = []

    def send(row: dict) -> dict:
        seen.append(row)
        return {"status": "sent", "symbol": row["symbol"]}

    out = drain_validated(knowledge, send, user_mode="live", now=NOW)
    assert out[0]["status"] == "sent"
    assert seen[0]["trading_mode"] == "mainnet"
    assert seen[0]["stop_px"] == "59400"
    assert knowledge.pending_intents() == []


def test_demo_drain_stays_testnet_venue(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    seen: list[dict] = []

    def send(row: dict) -> dict:
        seen.append(row)
        return {"status": "not_sent"}

    out = drain_validated(knowledge, send, user_mode="demo", now=NOW)
    assert out[0]["status"] == "failed"
    assert seen[0]["trading_mode"] == "testnet"
