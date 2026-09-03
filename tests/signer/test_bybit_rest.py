"""Live submit uses injected POST. Withdraw URL is refused. No real host call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from capitalizator.signer.bybit_rest import (
    MAIN_HOST,
    SUBMIT_PATH,
    cancel_open,
    sign,
    submit_limit,
)
from capitalizator.signer.cred import Cred, load_cred


def _cred() -> Cred:
    return Cred(public="pub", seed="seed")


def _order() -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "side": "buy",
        "qty": "0.001",
        "limit_px": "60000",
        "stop_px": "59400",
        "tp_px": "61200",
        "trading_mode": "mainnet",
    }


def test_sign_is_stable() -> None:
    got = sign(seed="seed", stamp="1", public="pub", window="5000", body="{}")
    assert got == sign(seed="seed", stamp="1", public="pub", window="5000", body="{}")
    assert len(got) == 64


def test_submit_limit_sent_on_retcode_zero() -> None:
    captured: list[tuple[str, bytes, dict[str, str]]] = []

    def post(url: str, body: bytes, headers: dict[str, str]) -> dict:
        captured.append((url, body, headers))
        return {"retCode": 0, "retMsg": "OK", "result": {"orderId": "x1"}}

    out = submit_limit(_cred(), _order(), post=post, now_ms=1)
    assert out["status"] == "sent"
    assert out["exchange_id"] == "x1"
    url, raw, headers = captured[0]
    assert url == MAIN_HOST + SUBMIT_PATH
    payload = json.loads(raw)
    assert payload["orderType"] == "Limit"
    assert payload["stopLoss"] == "59400"
    assert payload["timeInForce"] == "PostOnly"
    assert "X-BAPI-SIGN" in headers
    assert "withdraw" not in url


def test_submit_limit_refuses_non_mainnet() -> None:
    with pytest.raises(ValueError, match="mainnet"):
        submit_limit(_cred(), {**_order(), "trading_mode": "testnet"}, post=lambda *_: {})


def test_withdraw_host_is_refused() -> None:
    with pytest.raises(ValueError, match="withdraw"):
        submit_limit(
            _cred(),
            _order(),
            host="https://api.bybit.com/v5/asset/withdraw",
            post=lambda *_: {"retCode": 0, "result": {}},
        )


def test_cancel_open_posts_linear() -> None:
    def post(url: str, body: bytes, headers: dict[str, str]) -> dict:
        assert url.endswith("/v5/order/cancel-all")
        assert json.loads(body) == {"category": "linear"}
        return {"retCode": 0, "result": {}}

    out = cancel_open(_cred(), post=post, now_ms=1)
    assert out["status"] == "ok"


def test_load_cred_0600(tmp_path: Path) -> None:
    path = tmp_path / "cred"
    path.write_text("id=pub\nseed=priv\n", encoding="utf-8")
    path.chmod(0o600)
    got = load_cred(path)
    assert got.public == "pub"
    assert got.seed == "priv"


def test_load_cred_refuses_world_readable(tmp_path: Path) -> None:
    path = tmp_path / "cred"
    path.write_text("id=pub\nseed=priv\n", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        load_cred(path)
