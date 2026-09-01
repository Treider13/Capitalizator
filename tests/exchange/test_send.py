"""§11 send: demo → testnet POST, live → mainnet POST. Injected HTTP."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.exchange.client import MAINNET_REST, TESTNET_REST, ExchangeClient
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault, write_regular_text
from capitalizator.signer.process import drain_validated

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


class FakeHttp:
    def __init__(self, responses: list[dict]) -> None:
        self.calls: list[dict] = []
        self.responses = list(responses)

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        body: bytes | None = None,
        timeout: float = 8,
    ) -> dict:
        self.calls.append({"method": method, "url": url, "body": None if body is None else body.decode()})
        return self.responses.pop(0)


def _vault(tmp_path: Path):
    vault = init_vault(tmp_path / "desk")
    write_regular_text(vault.secrets / "bybit_api_key", "test-key\n")
    write_regular_text(vault.secrets / "bybit_api_secret", "test-secret\n")
    return vault


def _payload() -> dict:
    return {
        "symbol": "BTCUSDT",
        "side": "buy",
        "qty": "0.001",
        "entry": "100",
        "stop": "99",
        "tp": "102",
        "reduce_only_stop": True,
        "size_mult": "1",
    }


def test_demo_queue_posts_testnet(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    knowledge = open_knowledge(vault)
    knowledge.enqueue_intent(_payload(), created_ts=NOW.isoformat())
    http = FakeHttp([{"retCode": 0, "result": {"orderId": "d1"}}])
    client = ExchangeClient.from_vault(vault, http=http)
    out = drain_validated(
        knowledge,
        lambda row: client.send_order(row, user_mode="demo"),
        user_mode="demo",
        now=NOW,
    )
    assert out[0]["status"] == "sent"
    assert http.calls[0]["url"].startswith(TESTNET_REST)
    assert "/v5/order/create" in http.calls[0]["url"]
    assert knowledge.pending_intents() == []


def test_live_queue_posts_mainnet(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    knowledge = open_knowledge(vault)
    knowledge.enqueue_intent(_payload(), created_ts=NOW.isoformat())
    http = FakeHttp([{"retCode": 0, "result": {"orderId": "l1"}}])
    client = ExchangeClient.from_vault(vault, http=http)
    out = drain_validated(
        knowledge,
        lambda row: client.send_order(row, user_mode="live"),
        user_mode="live",
        now=NOW,
    )
    assert out[0]["status"] == "sent"
    assert http.calls[0]["url"].startswith(MAINNET_REST)
    assert "/v5/order/create" in http.calls[0]["url"]


def test_size_mult_halves_qty_on_the_wire(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    knowledge = open_knowledge(vault)
    payload = _payload()
    payload["size_mult"] = "0.5"
    knowledge.enqueue_intent(payload, created_ts=NOW.isoformat())
    http = FakeHttp([{"retCode": 0, "result": {"orderId": "q1"}}])
    client = ExchangeClient.from_vault(vault, http=http)
    drain_validated(
        knowledge,
        lambda row: client.send_order(row, user_mode="demo"),
        user_mode="demo",
        now=NOW,
    )
    assert "0.0005" in http.calls[0]["body"]
