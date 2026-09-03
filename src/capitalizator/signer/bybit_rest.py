"""Bybit linear private REST. Only the signer process calls this.

Limit + reduce-only stop. No withdraw. No asset transfer.
Host is official mainnet unless tests inject another.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.request import Request, urlopen

from capitalizator.signer.cred import Cred

MAIN_HOST = "https://api.bybit.com"
TEST_HOST = "https://api-testnet.bybit.com"
WINDOW = "5000"
SUBMIT_PATH = "/v5/order/create"
CANCEL_PATH = "/v5/order/cancel-all"
BLOCKED = ("/v5/asset/withdraw", "/asset/withdraw", "withdraw")
PostFn = Callable[[str, bytes, dict[str, str]], dict[str, Any]]


def sign(*, seed: str, stamp: str, public: str, window: str, body: str) -> str:
    payload = f"{stamp}{public}{window}{body}"
    return hmac.new(seed.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _qty(value: object) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _blocked(url: str) -> None:
    low = url.lower()
    if any(part in low for part in BLOCKED):
        raise ValueError("withdraw is forbidden")


def _http(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    _blocked(url)
    req = Request(url, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=10) as resp:  # noqa: S310 — host is fixed official API
        raw = json.loads(resp.read().decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("exchange body is not an object")
    return raw


def submit_limit(
    cred: Cred,
    order: dict[str, Any],
    *,
    host: str = MAIN_HOST,
    post: PostFn | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """POST linear limit with stop. Inject `post` in tests. No withdraw."""
    _blocked(host)
    if str(order.get("trading_mode") or "") != "mainnet":
        raise ValueError("submit_limit is mainnet only")
    stop = order.get("stop_px") or order.get("stop")
    if stop is None:
        raise ValueError("stop must be present")
    payload: dict[str, Any] = {
        "category": "linear",
        "symbol": str(order["symbol"]),
        "side": "Buy" if str(order["side"]).lower() == "buy" else "Sell",
        "orderType": "Limit",
        "qty": _qty(order.get("qty") or "0.001"),
        "price": _qty(order.get("limit_px") or order["entry"]),
        "timeInForce": "PostOnly",
        "stopLoss": _qty(stop),
        "reduceOnly": False,
        "positionIdx": 0,
    }
    tp = order.get("tp_px", order.get("tp"))
    if tp is not None:
        payload["takeProfit"] = _qty(tp)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    stamp = str(now_ms if now_ms is not None else int(time.time() * 1000))
    headers = {
        "Content-Type": "application/json",
        "X-BAPI-API-KEY": cred.public,
        "X-BAPI-TIMESTAMP": stamp,
        "X-BAPI-RECV-WINDOW": WINDOW,
        "X-BAPI-SIGN": sign(
            seed=cred.seed, stamp=stamp, public=cred.public, window=WINDOW, body=body
        ),
    }
    url = f"{host.rstrip('/')}{SUBMIT_PATH}"
    _blocked(url)
    sender = post or _http
    raw = sender(url, body.encode("utf-8"), headers)
    code = int(raw.get("retCode") if raw.get("retCode") is not None else 1)
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    if code == 0:
        return {
            "status": "sent",
            "symbol": payload["symbol"],
            "exchange_id": str(result.get("orderId") or ""),
            "stop_px": payload["stopLoss"],
        }
    return {
        "status": "failed",
        "reason": str(raw.get("retMsg") or "exchange refused"),
        "symbol": payload["symbol"],
    }


def cancel_open(
    cred: Cred,
    *,
    host: str = MAIN_HOST,
    post: PostFn | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Cancel linear opens. Dead-man / process exit. No withdraw."""
    _blocked(host)
    body = json.dumps({"category": "linear"}, separators=(",", ":"))
    stamp = str(now_ms if now_ms is not None else int(time.time() * 1000))
    headers = {
        "Content-Type": "application/json",
        "X-BAPI-API-KEY": cred.public,
        "X-BAPI-TIMESTAMP": stamp,
        "X-BAPI-RECV-WINDOW": WINDOW,
        "X-BAPI-SIGN": sign(
            seed=cred.seed, stamp=stamp, public=cred.public, window=WINDOW, body=body
        ),
    }
    url = f"{host.rstrip('/')}{CANCEL_PATH}"
    _blocked(url)
    sender = post or _http
    raw = sender(url, body.encode("utf-8"), headers)
    code = int(raw.get("retCode") if raw.get("retCode") is not None else 1)
    return {"status": "ok" if code == 0 else "failed", "ret": raw}
