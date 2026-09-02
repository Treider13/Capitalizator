"""The SDK signs exactly as Bybit documents; we do not reimplement HMAC ourselves.

https://bybit-exchange.github.io/docs/v5/guide#authentication:
  sign = HMAC_SHA256(secret, timestamp + api_key + recv_window + (queryString | jsonBody))
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

pybit = pytest.importorskip("pybit")


def test_pybit_hmac_matches_documented_formula() -> None:
    from pybit._http_manager import generate_signature
    from pybit.unified_trading import HTTP

    key, secret = "XXXXXXXXXX", "YYYYYYYYYYYYYYYYYYYYYYYYYY"
    session = HTTP(testnet=True, api_key=key, api_secret=secret, recv_window=5000)
    timestamp = 1672364262444
    body = '{"category":"linear","symbol":"BTCUSDT"}'
    got = session._auth(body, 5000, timestamp)
    expected = hmac.new(
        secret.encode(), f"{timestamp}{key}5000{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert got == expected
    assert generate_signature(False, secret, f"{timestamp}{key}5000{body}") == expected


def test_make_session_is_testnet_for_testnet_keys() -> None:
    from capitalizator.gateway.bybit import make_session
    from capitalizator.gateway.keys import Keys

    s = make_session(Keys(api_key="k1234567", api_secret="s", mode="testnet"))
    assert "api-testnet.bybit.com" in s.endpoint
    live = make_session(Keys(api_key="k1234567", api_secret="s", mode="live_sub"))
    assert "api-testnet" not in live.endpoint and "bybit.com" in live.endpoint
