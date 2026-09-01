"""§11: signer boot refuses if the API key can withdraw."""

from __future__ import annotations

from pathlib import Path

import pytest

from capitalizator.exchange.client import ExchangeClient, WithdrawEnabled, require_withdraw_off
from capitalizator.ops.vault import init_vault, write_regular_text


class FakeHttp:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
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
        return self.payload


def _client(tmp_path: Path, http: FakeHttp) -> ExchangeClient:
    vault = init_vault(tmp_path / "desk")
    write_regular_text(vault.secrets / "bybit_api_key", "test-key\n")
    write_regular_text(vault.secrets / "bybit_api_secret", "test-secret\n")
    return ExchangeClient.from_vault(vault, http=http)


def test_withdraw_on_refuses_boot(tmp_path: Path) -> None:
    http = FakeHttp(
        {
            "retCode": 0,
            "result": {"permissions": {"Wallet": ["AccountTransfer", "Withdraw"]}},
        }
    )
    client = _client(tmp_path, http)
    with pytest.raises(WithdrawEnabled, match="withdraw"):
        require_withdraw_off(client, user_mode="demo")
    assert any("query-api" in url or "withdraw" in url.lower() for url in http.calls)


def test_withdraw_off_allows_boot(tmp_path: Path) -> None:
    http = FakeHttp(
        {
            "retCode": 0,
            "result": {"permissions": {"Wallet": ["AccountTransfer"], "ContractTrade": ["Order"]}},
        }
    )
    client = _client(tmp_path, http)
    require_withdraw_off(client, user_mode="demo")
    assert http.calls
