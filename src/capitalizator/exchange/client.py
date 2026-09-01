"""Bybit v5 REST. Keys from Vault files. HTTP is injectable.

Hosts are here so signer/ and exec/ stay host-free (existing locks).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from capitalizator.ops.vault import Vault, load_vault, open_regular, write_regular_text

HttpFn = Callable[..., dict[str, Any]]

TESTNET_REST = "https://api-testnet.bybit.com"
MAINNET_REST = "https://api.bybit.com"
RECV_WINDOW = "5000"
HELLO_QTY = Decimal("0.001")
HELLO_OFFSET = Decimal("0.9")


class ExchangeError(ValueError):
    """Bybit retCode != 0 or a refused boot check."""


class WithdrawEnabled(ExchangeError):
    """API key can withdraw. Signer must not start."""


class VaultKeys:
    def __init__(self, key: str, secret: str) -> None:
        self.key = key
        self.secret = secret


def load_vault_keys(root: Path | Vault) -> VaultKeys:
    vault = root if isinstance(root, Vault) else load_vault(root)
    key = _read_secret(vault.secrets / "bybit_api_key")
    secret = _read_secret(vault.secrets / "bybit_api_secret")
    if not key or not secret:
        raise ExchangeError("vault keys missing")
    return VaultKeys(key, secret)


def _read_secret(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ExchangeError(f"secret missing: {path.name}")
    fd = open_regular(path)
    try:
        data = b""
        while True:
            chunk = __import__("os").read(fd, 4096)
            if not chunk:
                break
            data += chunk
    finally:
        __import__("os").close(fd)
    return data.decode("utf-8").strip()


def default_http(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: float = 8,
) -> dict[str, Any]:
    req = Request(url, data=body, method=method, headers=headers or {})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — host chosen by us
        return json.loads(resp.read().decode())


def public_mid(http: HttpFn | None = None, *, symbol: str = "BTCUSDT") -> Decimal:
    """Public testnet ticker. No key. Used only for hello distance from mid."""
    fn = http or default_http
    url = f"{TESTNET_REST}/v5/market/tickers?category=linear&symbol={symbol}"
    out = fn("GET", url, headers={}, body=None)
    if out.get("retCode") not in (0, None):
        raise ExchangeError(f"ticker retCode {out.get('retCode')}")
    rows = ((out.get("result") or {}).get("list") or [])
    if not rows or not isinstance(rows[0], dict):
        raise ExchangeError("ticker empty")
    mid = Decimal(str(rows[0].get("markPrice") or rows[0].get("lastPrice") or "0"))
    if mid <= 0:
        raise ExchangeError("ticker mid missing")
    return mid


def host_for(user_mode: str) -> str:
    if user_mode == "live":
        return MAINNET_REST
    if user_mode == "demo":
        return TESTNET_REST
    raise ValueError(f"send only in demo|live, got {user_mode!r}")


class ExchangeClient:
    def __init__(
        self,
        *,
        key: str,
        secret: str,
        http: HttpFn | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.key = key
        self.secret = secret
        self.http = http or default_http
        self.clock = clock or (lambda: int(time.time() * 1000))

    @classmethod
    def from_vault(cls, root: Path | Vault, *, http: HttpFn | None = None) -> ExchangeClient:
        keys = load_vault_keys(root)
        return cls(key=keys.key, secret=keys.secret, http=http)

    def send_order(self, payload: dict[str, Any], *, user_mode: str) -> dict[str, Any]:
        host = host_for(user_mode)
        qty = _qty_with_mult(payload)
        side = str(payload["side"])
        body = {
            "category": "linear",
            "symbol": str(payload["symbol"]),
            "side": "Buy" if side == "buy" else "Sell",
            "orderType": "Limit",
            "qty": str(qty),
            "price": str(payload.get("limit_px") or payload.get("entry") or payload.get("price")),
            "timeInForce": "GTC",
            "reduceOnly": False,
        }
        result = self._signed(host, "POST", "/v5/order/create", body)
        return {"status": "sent", "orderId": (result.get("result") or {}).get("orderId"), "host": host}

    def cancel_order(self, *, user_mode: str, symbol: str, order_id: str) -> dict[str, Any]:
        host = host_for(user_mode)
        result = self._signed(
            host,
            "POST",
            "/v5/order/cancel",
            {"category": "linear", "symbol": symbol, "orderId": order_id},
        )
        return {"status": "cancelled", "result": result.get("result")}

    def cancel_all(self, *, user_mode: str) -> dict[str, Any]:
        host = host_for(user_mode)
        result = self._signed(
            host,
            "POST",
            "/v5/order/cancel-all",
            {"category": "linear", "settleCoin": "USDT"},
        )
        return {"status": "cancelled", "result": result.get("result"), "host": host}

    def query_api(self, *, user_mode: str) -> dict[str, Any]:
        host = host_for(user_mode)
        return self._signed(host, "GET", "/v5/user/query-api", None)

    def _signed(
        self,
        host: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ts = str(self.clock())
        raw = "" if payload is None else json.dumps(payload, separators=(",", ":"))
        msg = f"{ts}{self.key}{RECV_WINDOW}{raw}"
        sign = hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        headers = {
            "X-BAPI-API-KEY": self.key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "Content-Type": "application/json",
        }
        body = None if method == "GET" else raw.encode()
        out = self.http(method, host + path, headers=headers, body=body)
        if out.get("retCode") not in (0, None):
            raise ExchangeError(f"bybit retCode {out.get('retCode')}: {out.get('retMsg')}")
        return out


def _qty_with_mult(payload: dict[str, Any]) -> Decimal:
    qty = Decimal(str(payload.get("qty") or HELLO_QTY))
    mult = Decimal(str(payload.get("size_mult") or "1"))
    if qty <= 0 or mult <= 0:
        raise ExchangeError("qty/size_mult must be > 0")
    return qty * mult


def testnet_hello(*args, **kwargs):  # pytest must not collect this name
    return _run_hello(*args, **kwargs)


testnet_hello.__test__ = False  # type: ignore[attr-defined]


def _run_hello(
    client: ExchangeClient,
    *,
    mid: Decimal,
    symbol: str = "BTCUSDT",
    qty: Decimal = HELLO_QTY,
) -> dict[str, Any]:
    """Limit far below mid, then cancel. Proves the testnet key can trade."""
    if mid <= 0:
        raise ExchangeError("mid must be > 0")
    far = (mid * HELLO_OFFSET).quantize(Decimal("0.01"))
    created = client.send_order(
        {
            "symbol": symbol,
            "side": "buy",
            "qty": str(qty),
            "limit_px": str(far),
            "size_mult": "1",
        },
        user_mode="demo",
    )
    order_id = str(created.get("orderId") or "")
    if not order_id:
        raise ExchangeError("hello create returned no orderId")
    client.cancel_order(user_mode="demo", symbol=symbol, order_id=order_id)
    return {"status": "sent", "hello": True, "orderId": order_id, "limit_px": str(far)}


def require_withdraw_off(client: ExchangeClient, *, user_mode: str = "demo") -> None:
    """Refuse boot if the key can withdraw. Analog of /v5/user/query-api."""
    out = client.query_api(user_mode=user_mode)
    result = out.get("result") or {}
    perms = result.get("permissions") or {}
    wallet = perms.get("Wallet") or perms.get("wallet") or []
    if isinstance(wallet, str):
        wallet = [wallet]
    names = {str(x) for x in wallet}
    if "Withdraw" in names or "withdraw" in names:
        raise WithdrawEnabled("withdraw must be off")


def write_key_files(vault: Vault, *, key: str, secret: str) -> None:
    write_regular_text(vault.secrets / "bybit_api_key", key)
    write_regular_text(vault.secrets / "bybit_api_secret", secret)
