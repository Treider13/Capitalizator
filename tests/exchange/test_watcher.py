"""§11 dead-man: external watcher cancel_all when signer heartbeat is stale."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from capitalizator.exchange.client import MAINNET_REST, TESTNET_REST, ExchangeClient
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import set_user_mode
from capitalizator.ops.vault import init_vault, write_regular_text
from capitalizator.signer.process import HEARTBEAT_S, write_heartbeat
from capitalizator.signer.watch import WATCH_STALE_S, exchange_cancel_all, watcher_tick

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        body: bytes | None = None,
        timeout: float = 8,
    ) -> dict:
        self.calls.append(url)
        return {"retCode": 0, "result": {}}


def test_stale_heartbeat_calls_cancel_all(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    write_heartbeat(knowledge, NOW - timedelta(seconds=WATCH_STALE_S + 1))
    hits: list[int] = []
    fired = watcher_tick(
        knowledge,
        lambda: hits.append(1),
        now=NOW,
    )
    assert fired is True
    assert hits == [1]


def test_fresh_heartbeat_does_not_cancel(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    write_heartbeat(knowledge, NOW)
    hits: list[int] = []
    fired = watcher_tick(knowledge, lambda: hits.append(1), now=NOW + timedelta(seconds=10))
    assert fired is False
    assert hits == []


def test_missing_heartbeat_is_stale(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    hits: list[int] = []
    assert watcher_tick(knowledge, lambda: hits.append(1), now=NOW) is True
    assert hits == [1]


def test_watch_stale_is_three_heartbeats() -> None:
    assert WATCH_STALE_S == HEARTBEAT_S * 3


def test_watcher_cancel_all_hits_exchange(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    write_regular_text(vault.secrets / "bybit_api_key", "test-key\n")
    write_regular_text(vault.secrets / "bybit_api_secret", "test-secret\n")
    http = FakeHttp()
    client = ExchangeClient.from_vault(vault, http=http)
    knowledge = open_knowledge(vault)
    watcher_tick(
        knowledge,
        lambda: client.cancel_all(user_mode="demo"),
        now=NOW,
    )
    assert any("/v5/order/cancel-all" in url for url in http.calls)
    assert http.calls[0].startswith(TESTNET_REST)


def test_exchange_cancel_all_when_mode_off_still_hits_testnet(tmp_path: Path, monkeypatch) -> None:
    """Watcher often boots at user_mode=off. SIGKILL leftover must still cancel testnet."""
    vault = init_vault(tmp_path / "desk")
    write_regular_text(vault.secrets / "bybit_api_key", "test-key\n")
    write_regular_text(vault.secrets / "bybit_api_secret", "test-secret\n")
    http = FakeHttp()
    monkeypatch.setattr(
        "capitalizator.exchange.client.ExchangeClient.from_vault",
        classmethod(lambda cls, root, **kw: ExchangeClient(key="k", secret="s", http=http)),
    )
    assert exchange_cancel_all(vault) == "demo"
    assert http.calls[0].startswith(TESTNET_REST)
    assert "/v5/order/cancel-all" in http.calls[0]


def test_exchange_cancel_all_live_hits_mainnet(tmp_path: Path, monkeypatch) -> None:
    vault = init_vault(tmp_path / "desk")
    write_regular_text(vault.secrets / "bybit_api_key", "test-key\n")
    write_regular_text(vault.secrets / "bybit_api_secret", "test-secret\n")
    set_user_mode(vault, "live", ack=True)
    http = FakeHttp()
    monkeypatch.setattr(
        "capitalizator.exchange.client.ExchangeClient.from_vault",
        classmethod(lambda cls, root, **kw: ExchangeClient(key="k", secret="s", http=http)),
    )
    assert exchange_cancel_all(vault) == "live"
    assert http.calls[0].startswith(MAINNET_REST)
