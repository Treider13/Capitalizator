"""Official Bybit REST/WS adapter. Demo uses mainnet market data and demo funds."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from capitalizator.fusion.config import Config
from capitalizator.fusion.risk import Instrument


class VenueError(RuntimeError):
    def __init__(self, code: int, message: str = "venue_rejected") -> None:
        super().__init__(f"{message}: {code}")
        self.code = code


def credentials(root: Path, mode: str) -> tuple[str, str] | None:
    if mode not in {"demo", "live"}:
        raise ValueError("only demo/live credentials accepted")
    path = root / "secrets" / f"{mode}.json"
    if path.is_symlink():
        raise ValueError("credential file may not be a symlink")
    if path.is_file():
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("credential file must have mode 0600")
        body = json.loads(path.read_text())
        if body.get("mode") != mode:
            raise ValueError("credential mode mismatch")
        return str(body["key"]), str(body["secret"])
    prefix = "CAP_" + mode.upper()
    key, secret = os.environ.get(prefix + "_KEY"), os.environ.get(prefix + "_SECRET")
    return (key, secret) if key and secret else None


class Bybit:
    def __init__(self, mode: str, keys: tuple[str, str], config: Config) -> None:
        from pybit.unified_trading import HTTP

        if mode not in {"demo", "live"}:
            raise ValueError("only Bybit Demo and Live are supported")
        self.mode, self.config = mode, config
        self.keys = keys
        self.http = HTTP(
            testnet=False,
            demo=mode == "demo",
            api_key=keys[0],
            api_secret=keys[1],
            timeout=config.http_timeout_s,
            max_retries=1,
            force_retry=False,
            log_requests=False,
        )

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        try:
            result = getattr(self.http, method)(**params)
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            # HTTP errors/timeouts remain unknown, business rejections are explicit.
            if isinstance(code, int) and code >= 10000:
                raise VenueError(code) from None
            raise RuntimeError(f"Bybit {method} transport failure ({type(exc).__name__})") from None
        if int(result.get("retCode", -1)) != 0:
            raise VenueError(int(result.get("retCode", -1)))
        return dict(result["result"])

    def pages(self, method: str, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = ""
        seen: set[str] = set()
        while True:
            page = self.call(method, **params, **({"cursor": cursor} if cursor else {}))
            out.extend(page.get("list") or [])
            cursor = page.get("nextPageCursor") or ""
            if not cursor:
                return out
            if cursor in seen:
                raise RuntimeError("Bybit pagination cursor repeated")
            seen.add(cursor)

    def instruments(self) -> dict[str, Instrument]:
        out = {}
        for symbol in self.config.symbols:
            rows = self.call("get_instruments_info", category="linear", symbol=symbol)["list"]
            if not rows or rows[0].get("status") != "Trading":
                raise ValueError(f"{symbol} is not trading")
            if self.mode == "demo":
                # Demo's published endpoint list does not include fee-rate access.
                # Explicit configurable estimate; real execution fees are journalled.
                rates = (self.config.demo_maker_fee, self.config.demo_taker_fee)
            else:
                fees = self.call("get_fee_rates", category="linear", symbol=symbol)["list"][0]
                rates = (float(fees["makerFeeRate"]), float(fees["takerFeeRate"]))
            out[symbol] = Instrument.parse(rows[0], rates)
        return out

    def account(self) -> tuple[float, list[Any], list[Any]]:
        wallet = self.call("get_wallet_balance", accountType="UNIFIED")["list"][0]
        equity = float(wallet["totalEquity"])
        positions = self.pages("get_positions", category="linear", settleCoin="USDT", limit=200)
        orders = self.pages("get_open_orders", category="linear", settleCoin="USDT", limit=50)
        return equity, positions, orders

    def executions(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return self.pages(
            "get_executions", category="linear", startTime=start_ms, endTime=end_ms, limit=100
        )

    def place(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            self.call(
                "set_leverage",
                category="linear",
                symbol=body["symbol"],
                buyLeverage=body["leverage"],
                sellLeverage=body["leverage"],
            )
        except VenueError as exc:
            if exc.code != 110043:  # leverage already set
                raise
        return self.call(
            "place_order",
            category="linear",
            symbol=body["symbol"],
            side=body["side"],
            orderType="Limit",
            timeInForce="PostOnly",
            qty=body["qty"],
            price=body["price"],
            orderLinkId=body["orderLinkId"],
            positionIdx=0,
            stopLoss=body["stop"],
            slTriggerBy="MarkPrice",
            tpslMode="Full",
        )

    def lookup(self, symbol: str, ident: str) -> dict[str, Any] | None:
        for method in ("get_open_orders", "get_order_history"):
            rows = self.call(method, category="linear", symbol=symbol, orderLinkId=ident)["list"]
            if rows:
                return dict(rows[0])
        return None

    def cancel(self, symbol: str, ident: str) -> None:
        try:
            self.call("cancel_order", category="linear", symbol=symbol, orderLinkId=ident)
        except VenueError as exc:
            if exc.code != 110001:  # not found still requires reconciliation
                raise

    def close_position(self, pos: dict[str, Any], ident: str) -> None:
        self.call(
            "place_order",
            category="linear",
            symbol=pos["symbol"],
            side="Sell" if pos["side"] == "Buy" else "Buy",
            orderType="Market",
            qty=str(pos["size"]),
            positionIdx=int(pos.get("positionIdx") or 0),
            reduceOnly=True,
            orderLinkId=ident,
        )

    def stop(self, symbol: str, price: float) -> None:
        self.call(
            "set_trading_stop",
            category="linear",
            symbol=symbol,
            positionIdx=0,
            tpslMode="Full",
            stopLoss=str(price),
            slTriggerBy="MarkPrice",
        )

    def private_ws(self, callback: Any) -> Any:
        from pybit.unified_trading import WebSocket

        ws = WebSocket(
            testnet=False,
            demo=self.mode == "demo",
            channel_type="private",
            api_key=self.keys[0],
            api_secret=self.keys[1],
            retries=3,
        )
        ws.execution_stream(callback)
        ws.order_stream(callback)
        ws.position_stream(callback)
        ws.wallet_stream(callback)
        return ws
