"""Bybit v5 execution gateway on the official `pybit` SDK (§5.2).

pybit (bybit-exchange/pybit, MIT) does HMAC-SHA256 signing, X-BAPI-* headers,
recv_window and retries; we do not reimplement any of that. The HTTP session is
injected so every method is unit-tested against a fake with the documented
response shapes (retCode/retMsg/result), and the same code talks to testnet or
mainnet by construction (`Keys.mode`).

Endpoints used (https://bybit-exchange.github.io/docs/v5/intro):
  market/time, market/instruments-info, account/wallet-balance, account/fee-rate,
  position/list, position/set-leverage, position/trading-stop,
  order/create, order/amend, order/cancel-all, order/realtime.

Rules baked in:
  * every entry carries a deterministic orderLinkId → a retry cannot double-fill;
  * an entry is refused after its `valid_until` (D-38, stale price);
  * the stop-loss is attached to the entry order itself (Full mode, MarkPrice
    trigger) so protection exists the instant the fill happens;
  * after the fill: reduce-only +1R limit for half; trailing via trading-stop;
  * `cancel_entries` uses orderFilter=Order and never cancels TP/SL orders;
  * no method reads a key from anywhere but the injected session.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import blake2s
from typing import Any

from capitalizator.gateway.keys import Keys

CATEGORY = "linear"


class GatewayError(RuntimeError):
    pass


def order_link_id(payload: Mapping[str, Any]) -> str:
    """Deterministic per intent: same intent → same id → the venue rejects a duplicate.
    Bybit allows up to 36 chars; we use 32 hex."""
    parts = (
        str(payload.get("touch_id") or payload.get("intent_id") or ""),
        str(payload.get("symbol") or ""),
        str(payload.get("side") or ""),
        str(payload.get("entry") or payload.get("limit_px") or ""),
        str(payload.get("stop") or payload.get("stop_px") or ""),
        str(payload.get("qty") or ""),
    )
    return blake2s("|".join(parts).encode(), digest_size=16).hexdigest()


def make_session(keys: Keys) -> Any:
    """Real pybit session. Imported lazily so the desk never loads pybit."""
    from pybit.unified_trading import HTTP

    return HTTP(
        testnet=keys.testnet,
        api_key=keys.api_key,
        api_secret=keys.api_secret,
        recv_window=5000,
    )


def _ok(resp: Mapping[str, Any], *, what: str) -> dict[str, Any]:
    code = resp.get("retCode")
    if code not in (0, "0", None):
        raise GatewayError(f"{what}: retCode={code} retMsg={resp.get('retMsg')}")
    result = resp.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


class BybitGateway:
    def __init__(
        self,
        session: Any,
        *,
        mode: str,
        category: str = CATEGORY,
        clock: Callable[[], datetime] | None = None,
        position_idx: int = 0,
    ) -> None:
        if mode not in {"testnet", "live_sub", "live_main"}:
            raise ValueError("mode must be testnet|live_sub|live_main")
        self.s = session
        self.mode = mode
        self.category = category
        self.position_idx = position_idx
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self.log: list[dict[str, Any]] = []
        self._lev_set: set[str] = set()

    # --- bookkeeping -------------------------------------------------------------------
    def _record(self, kind: str, **fields: Any) -> dict[str, Any]:
        row = {"kind": kind, "at": self._clock().isoformat(), **fields}
        self.log.append(row)
        if len(self.log) > 2000:
            del self.log[: len(self.log) - 2000]
        return row

    # --- reads -------------------------------------------------------------------------
    def server_time(self) -> datetime:
        res = _ok(self.s.get_server_time(), what="server_time")
        nano = res.get("timeNano")
        sec = res.get("timeSecond")
        if nano:
            return datetime.fromtimestamp(int(nano) / 1e9, tz=UTC)
        return datetime.fromtimestamp(int(sec), tz=UTC)

    def instruments(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"category": self.category, "limit": 1000}
            if cursor:
                kwargs["cursor"] = cursor
            res = _ok(self.s.get_instruments_info(**kwargs), what="instruments")
            out.extend(res.get("list") or [])
            cursor = res.get("nextPageCursor") or None
            if not cursor:
                break
        return out

    def wallet_equity(self) -> Decimal:
        res = _ok(self.s.get_wallet_balance(accountType="UNIFIED"), what="wallet")
        rows = res.get("list") or []
        if not rows:
            raise GatewayError("wallet: empty list")
        total = rows[0].get("totalEquity")
        if total in (None, ""):
            raise GatewayError("wallet: totalEquity missing")
        return Decimal(str(total))

    def fee_rate(self, symbol: str) -> tuple[Decimal, Decimal]:
        res = _ok(self.s.get_fee_rates(category=self.category, symbol=symbol), what="fee_rate")
        rows = res.get("list") or []
        if not rows:
            raise GatewayError("fee_rate: empty list")
        return Decimal(str(rows[0]["makerFeeRate"])), Decimal(str(rows[0]["takerFeeRate"]))

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"category": self.category}
        if symbol:
            kwargs["symbol"] = symbol
        else:
            kwargs["settleCoin"] = "USDT"
        res = _ok(self.s.get_positions(**kwargs), what="positions")
        return list(res.get("list") or [])

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"category": self.category, "openOnly": 0}
        if symbol:
            kwargs["symbol"] = symbol
        else:
            kwargs["settleCoin"] = "USDT"
        res = _ok(self.s.get_open_orders(**kwargs), what="open_orders")
        return list(res.get("list") or [])

    # --- writes --------------------------------------------------------------------------
    def set_leverage(self, symbol: str, lev: Decimal) -> None:
        key = f"{symbol}:{lev}"
        if key in self._lev_set:
            return
        try:
            _ok(
                self.s.set_leverage(
                    category=self.category,
                    symbol=symbol,
                    buyLeverage=str(lev),
                    sellLeverage=str(lev),
                ),
                what="set_leverage",
            )
        except GatewayError as exc:
            # 110043 = leverage not modified: already at this value
            if "110043" not in str(exc):
                raise
        self._lev_set.add(key)
        self._record("set_leverage", symbol=symbol, lev=str(lev))

    def send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Queue drain callback: sized desk intent → post-only limit with attached SL.

        Refuses: stale (`valid_until` passed), unsized, stop on the wrong side.
        Returns {"status": "sent"|"rejected", ...}. Never raises into the drain.
        """
        try:
            return self._send(payload)
        except Exception as exc:  # GatewayError, pybit exceptions, network errors
            self._record("send_failed", error=str(exc), symbol=payload.get("symbol"))
            return {"status": "failed", "error": str(exc)}

    def _send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        symbol = str(payload["symbol"])
        side = str(payload["side"]).lower()
        qty = payload.get("qty")
        if qty in (None, "", "0"):
            raise GatewayError("intent not sized")
        entry = Decimal(str(payload.get("limit_px", payload.get("entry"))))
        stop = Decimal(str(payload.get("stop_px", payload.get("stop"))))
        if side == "buy" and stop >= entry or side == "sell" and stop <= entry:
            raise GatewayError("stop on the wrong side of entry")
        valid_until = payload.get("valid_until")
        now = self._clock()
        if valid_until:
            deadline = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
            if now > deadline:
                self._record("send_stale", symbol=symbol, valid_until=str(valid_until))
                return {"status": "rejected", "reason": "stale_intent", "valid_until": valid_until}
        lev = payload.get("lev")
        if lev:
            self.set_leverage(symbol, Decimal(str(lev)))
        link = order_link_id(payload)
        req = {
            "category": self.category,
            "symbol": symbol,
            "side": "Buy" if side == "buy" else "Sell",
            "orderType": "Limit",
            "qty": str(qty),
            "price": str(entry),
            "timeInForce": "PostOnly",
            "orderLinkId": link,
            "positionIdx": self.position_idx,
            "stopLoss": str(stop),
            "slTriggerBy": "MarkPrice",
            "tpslMode": "Full",
        }
        try:
            res = _ok(self.s.place_order(**req), what="place_order")
        except GatewayError as exc:
            if "110072" in str(exc) or "duplicate" in str(exc).lower():
                # orderLinkId already used → this intent is already on the venue
                self._record("send_duplicate", symbol=symbol, orderLinkId=link)
                return {"status": "sent", "orderLinkId": link, "duplicate": True}
            raise
        row = self._record(
            "entry_sent",
            symbol=symbol,
            side=side,
            qty=str(qty),
            price=str(entry),
            stop=str(stop),
            orderLinkId=link,
            orderId=res.get("orderId"),
        )
        return {
            "status": "sent",
            "orderId": res.get("orderId"),
            "orderLinkId": link,
            "symbol": symbol,
            "side": side,
            "qty": str(qty),
            "price": str(entry),
            "stop": str(stop),
            "at": row["at"],
        }

    def place_half_tp(
        self, *, symbol: str, side: str, qty: Decimal, price: Decimal, link: str
    ) -> dict[str, Any]:
        """Reduce-only limit for the +1R half (law 1.6.3). `side` is the POSITION side."""
        res = _ok(
            self.s.place_order(
                category=self.category,
                symbol=symbol,
                side="Sell" if side == "buy" else "Buy",
                orderType="Limit",
                qty=str(qty),
                price=str(price),
                timeInForce="GTC",
                reduceOnly=True,
                orderLinkId=f"{link[:24]}-tp1",
                positionIdx=self.position_idx,
            ),
            what="place_half_tp",
        )
        self._record("half_tp_sent", symbol=symbol, qty=str(qty), price=str(price))
        return res

    def amend_stop(self, symbol: str, new_stop: Decimal) -> dict[str, Any]:
        res = _ok(
            self.s.set_trading_stop(
                category=self.category,
                symbol=symbol,
                tpslMode="Full",
                positionIdx=self.position_idx,
                stopLoss=str(new_stop),
                slTriggerBy="MarkPrice",
            ),
            what="amend_stop",
        )
        self._record("stop_amended", symbol=symbol, stop=str(new_stop))
        return res

    def set_trailing(
        self, symbol: str, distance: Decimal, active_price: Decimal | None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "category": self.category,
            "symbol": symbol,
            "tpslMode": "Full",
            "positionIdx": self.position_idx,
            "trailingStop": str(distance),
        }
        if active_price is not None:
            kwargs["activePrice"] = str(active_price)
        res = _ok(self.s.set_trading_stop(**kwargs), what="set_trailing")
        self._record(
            "trailing_set", symbol=symbol, distance=str(distance), active=str(active_price)
        )
        return res

    def cancel_entries(self, symbol: str | None = None, *, reason: str = "") -> dict[str, Any]:
        """Cancel normal (entry / reduce-only limit) orders. TP/SL orders are untouched."""
        kwargs: dict[str, Any] = {"category": self.category, "orderFilter": "Order"}
        if symbol:
            kwargs["symbol"] = symbol
        else:
            kwargs["settleCoin"] = "USDT"
        res = _ok(self.s.cancel_all_orders(**kwargs), what="cancel_entries")
        self._record(
            "entries_cancelled", symbol=symbol, reason=reason, n=len(res.get("list") or [])
        )
        return res

    def flatten(self, symbol: str, *, reason: str = "flatten") -> dict[str, Any]:
        """Cancel entries, then market reduce-only for the whole position, then re-read."""
        self.cancel_entries(symbol, reason=reason)
        before = [p for p in self.positions(symbol) if Decimal(str(p.get("size") or "0")) > 0]
        sent: list[dict[str, Any]] = []
        for pos in before:
            side = str(pos.get("side") or "").lower()
            res = _ok(
                self.s.place_order(
                    category=self.category,
                    symbol=symbol,
                    side="Sell" if side == "buy" else "Buy",
                    orderType="Market",
                    qty=str(pos["size"]),
                    reduceOnly=True,
                    positionIdx=int(pos.get("positionIdx") or self.position_idx),
                ),
                what="flatten",
            )
            sent.append(res)
        after = [p for p in self.positions(symbol) if Decimal(str(p.get("size") or "0")) > 0]
        row = self._record(
            "flatten", symbol=symbol, reason=reason, closed=len(sent), left=len(after)
        )
        return {
            "status": "flat" if not after else "partial",
            "closed": sent,
            "left": after,
            "at": row["at"],
        }

    # --- hello ----------------------------------------------------------------------------
    def hello(self, *, symbol: str = "BTCUSDT", probe_order: bool = False) -> dict[str, Any]:
        """Prove the key works, step by step. Each step is ok/err; nothing is inferred."""
        steps: dict[str, Any] = {"mode": self.mode}

        def step(name: str, fn: Callable[[], Any]) -> None:
            try:
                steps[name] = {"ok": True, "value": fn()}
            except Exception as exc:  # report, do not hide
                steps[name] = {"ok": False, "error": str(exc)}

        def skew() -> str:
            srv = self.server_time()
            return str(int((self._clock() - srv).total_seconds() * 1000)) + "ms"

        step("server_time_skew", skew)
        step("wallet_equity", lambda: str(self.wallet_equity()))
        step("positions", lambda: len(self.positions()))
        step("fee_rate", lambda: [str(x) for x in self.fee_rate(symbol)])
        step("instruments", lambda: len(self.instruments()))
        if probe_order:
            def probe() -> dict[str, Any]:
                # far-from-market post-only, then cancel: proves trade permission on a key
                res = _ok(
                    self.s.place_order(
                        category=self.category,
                        symbol=symbol,
                        side="Buy",
                        orderType="Limit",
                        qty="0.001",
                        price="1",
                        timeInForce="PostOnly",
                        orderLinkId=f"hello-{int(self._clock().timestamp())}",
                        positionIdx=self.position_idx,
                    ),
                    what="probe_place",
                )
                _ok(
                    self.s.cancel_order(
                        category=self.category, symbol=symbol, orderId=res.get("orderId")
                    ),
                    what="probe_cancel",
                )
                return {"orderId": res.get("orderId"), "cancelled": True}

            step("probe_order", probe)
        steps["ok"] = all(v.get("ok") for k, v in steps.items() if isinstance(v, dict))
        self._record("hello", ok=steps["ok"])
        return steps
