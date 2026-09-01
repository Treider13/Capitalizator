"""§11 hello: limit far from mid + cancel. Injected HTTP. No live key."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.exchange.client import TESTNET_REST, ExchangeClient
from capitalizator.exchange.client import testnet_hello as run_hello
from capitalizator.ops.product import hello_recorded, mark_hello
from capitalizator.ops.vault import init_vault, write_regular_text


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
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": None if body is None else body.decode(),
            }
        )
        if not self.responses:
            raise AssertionError(f"unexpected HTTP {method} {url}")
        return self.responses.pop(0)


def _keys(vault_root: Path) -> None:
    vault = init_vault(vault_root)
    write_regular_text(vault.secrets / "bybit_api_key", "test-key\n")
    write_regular_text(vault.secrets / "bybit_api_secret", "test-secret\n")


def test_hello_posts_limit_far_from_mid_then_cancel(tmp_path: Path) -> None:
    _keys(tmp_path / "desk")
    http = FakeHttp(
        [
            {"retCode": 0, "result": {"orderId": "hello-1"}},
            {"retCode": 0, "result": {"orderId": "hello-1"}},
        ]
    )
    client = ExchangeClient.from_vault(tmp_path / "desk", http=http)
    mid = Decimal("100000")
    out = run_hello(client, mid=mid, symbol="BTCUSDT")
    assert out["status"] == "sent"
    assert out["hello"] is True
    assert len(http.calls) == 2
    create, cancel = http.calls
    assert create["method"] == "POST"
    assert create["url"].startswith(TESTNET_REST)
    assert "/v5/order/create" in create["url"]
    assert "90000" in create["body"]  # mid * 0.9
    assert cancel["method"] == "POST"
    assert "/v5/order/cancel" in cancel["url"]
    vault = init_vault(tmp_path / "desk")
    mark_hello(vault, ok=True)
    assert hello_recorded(vault) is True


def test_hello_failure_does_not_mark(tmp_path: Path) -> None:
    _keys(tmp_path / "desk")
    http = FakeHttp([{"retCode": 10001, "retMsg": "rejected"}])
    client = ExchangeClient.from_vault(tmp_path / "desk", http=http)
    with pytest.raises(Exception, match="retCode|rejected|hello"):
        run_hello(client, mid=Decimal("100000"))
    assert hello_recorded(init_vault(tmp_path / "desk")) is False
