"""Bybit v5 execution gateway on the official `pybit` SDK (§5.2).

pybit (bybit-exchange/pybit, MIT) does HMAC/RSA signing, X-BAPI-* headers,
recv_window and retries; we do not reimplement any of that. The HTTP session is
injected so every method is unit-tested against a fake, and the same code talks
to testnet or mainnet by construction (`Keys.mode`).

pybit contract (verified against pybit 5.17 `_http_manager.py`): a non-zero
`retCode` is **raised** as `pybit.exceptions.InvalidRequestError` (fields
`status_code` = retCode, `message`), HTTP/transport failures as
`FailedRequestError`; a dict with `retCode != 0` only reaches the caller when the
session was built with `ignore_codes`. `_call` normalises both worlds into
`GatewayError(code=…, kind=venue|network|local)` so every branch below is real.

Endpoints used (https://bybit-exchange.github.io/docs/v5/intro):
  market/time, market/instruments-info, market/tickers, account/wallet-balance,
  account/fee-rate, position/list, position/set-leverage, position/trading-stop,
  order/create, order/cancel, order/cancel-all, order/realtime, order/history.

Rules baked in:
  * every queue row carries its own orderLinkId → a retry of the same row cannot
    double-fill (110072 = already on the venue, reported as such, never `failed`);
  * an entry is refused after its `valid_until` (D-38, stale price);
  * the stop-loss is attached to the entry order itself (Full mode, MarkPrice
    trigger) so protection exists the instant the fill happens;
  * after the fill: reduce-only +1R limit for half; trailing via trading-stop;
  * `cancel_entries` uses orderFilter=Order and never cancels TP/SL orders;
  * a transport failure *after* place_order was issued is `unknown`, not
    `failed`: the order may exist. `resolve_unknown` asks the venue by link id;
    absent + still-valid is re-sent under the same link (signer, bounded);
    a recorded `orderLinkId` on the payload is the identity of that retry;
  * no method reads a key from anywhere but the injected session.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from hashlib import blake2s
from time import sleep as _sleep
from typing import Any, Literal

from capitalizator.gateway.keys import MODES, Keys

CATEGORY = "linear"

# Bybit v5 return codes we branch on (docs/v5/error).
CODE_LEVERAGE_NOT_MODIFIED = 110043
CODE_DUPLICATE_LINK_ID = 110072
CODE_ORDER_NOT_FOUND = 110001
# Post-only that would have crossed the book is cancelled by the venue, not filled.
CODE_POST_ONLY_WOULD_TAKE = 30208
# Bybit Demo Trading does not implement /v5/account/fee-rate (retCode 10001).
# VIP0 USDT-perp defaults; live/testnet still require the real endpoint.
DEMO_FEE_FALLBACK = (Decimal("0.0002"), Decimal("0.00055"))

ErrorKind = Literal["venue", "network", "local"]


class GatewayError(RuntimeError):
    """One error type for the whole gateway. `code` is the Bybit retCode when known."""

    def __init__(
        self,
        what: str,
        *,
        code: int | None = None,
        msg: str = "",
        kind: ErrorKind = "venue",
    ) -> None:
        self.what = what
        self.code = code
        self.msg = msg
        self.kind = kind
        tail = f" retCode={code}" if code is not None else ""
        super().__init__(f"{what}:{tail} {msg}".rstrip())


def _int_or_none(raw: object) -> int | None:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def from_exception(exc: BaseException, *, what: str) -> GatewayError:
    """Map pybit / transport exceptions onto GatewayError. Never returns None."""
    if isinstance(exc, GatewayError):
        return exc
    name = type(exc).__name__
    if name == "InvalidRequestError":
        return GatewayError(
            what,
            code=_int_or_none(getattr(exc, "status_code", None)),
            msg=str(getattr(exc, "message", exc)),
            kind="venue",
        )
    if name == "FailedRequestError":
        return GatewayError(
            what,
            code=_int_or_none(getattr(exc, "status_code", None)),
            msg=str(getattr(exc, "message", exc)),
            kind="network",
        )
    return GatewayError(what, msg=f"{name}: {exc}", kind="network")


def order_link_id(payload: Mapping[str, Any]) -> str:
    """Deterministic per queue row: the row id is the identity, so a retry of the
    same row hits 110072 on the venue instead of a second fill. Two rows with the
    same content (same zone on two days) get different ids. 32 hex ≤ 36 chars."""
    parts = (
        str(payload.get("intent_id") or payload.get("touch_id") or ""),
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

    # demo=True → api-demo.bybit.com (Bybit Demo Trading, mainnet data, simulated
    # funds); testnet=True → api-testnet.bybit.com; both False → mainnet (live keys).
    return HTTP(
        testnet=keys.testnet,
        demo=keys.demo,
        api_key=keys.api_key,
        api_secret=keys.api_secret,
        recv_window=5000,
    )


def _ok(resp: Mapping[str, Any], *, what: str) -> dict[str, Any]:
    code = resp.get("retCode")
    if code not in (0, "0", None):
        raise GatewayError(what, code=_int_or_none(code), msg=str(resp.get("retMsg") or ""))
    result = resp.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


def _round_step(value: Decimal, step: Decimal, *, up: bool = False) -> Decimal:
    if step <= 0:
        return value
    q = (value / step).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)
    return (q * step).quantize(step)


class BybitGateway:
    def __init__(
        self,
        session: Any,
        *,
        mode: str,
        category: str = CATEGORY,
        clock: Callable[[], datetime] | None = None,
        position_idx: int = 0,
        sleep: Callable[[float], None] = _sleep,
        settle_reads: int = 3,
        settle_wait_s: float = 0.3,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")
        self.s = session
        self.mode = mode
        self.category = category
        self.position_idx = position_idx
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._sleep = sleep
        self.settle_reads = max(1, settle_reads)
        self.settle_wait_s = settle_wait_s
        self.log: list[dict[str, Any]] = []
        self._lev_set: set[str] = set()
        self.fee_rates: dict[str, tuple[Decimal, Decimal]] = {}

    # --- plumbing ------------------------------------------------------------------------
    def _call(self, method: str, *, what: str, **kwargs: Any) -> dict[str, Any]:
        """Call a pybit session method; exceptions and retCode dicts → GatewayError."""
        fn = getattr(self.s, method)
        try:
            resp = fn(**kwargs)
        except Exception as exc:  # pybit InvalidRequestError / FailedRequestError / socket
            raise from_exception(exc, what=what) from exc
        if not isinstance(resp, Mapping):
            raise GatewayError(
                what, msg=f"unexpected response {type(resp).__name__}", kind="network"
            )
        return _ok(resp, what=what)

    def _record(self, kind: str, **fields: Any) -> dict[str, Any]:
        row = {"kind": kind, "at": self._clock().isoformat(), **fields}
        self.log.append(row)
        if len(self.log) > 2000:
            del self.log[: len(self.log) - 2000]
        return row

    # --- reads -------------------------------------------------------------------------
    def server_time(self) -> datetime:
        res = self._call("get_server_time", what="server_time")
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
            res = self._call("get_instruments_info", what="instruments", **kwargs)
            out.extend(res.get("list") or [])
            cursor = res.get("nextPageCursor") or None
            if not cursor:
                break
        return out

    def instrument(self, symbol: str) -> dict[str, Any]:
        res = self._call(
            "get_instruments_info", what="instrument", category=self.category, symbol=symbol
        )
        rows = res.get("list") or []
        if not rows:
            raise GatewayError("instrument", msg=f"{symbol} not listed", kind="local")
        return dict(rows[0])

    def tickers(self) -> list[dict[str, Any]]:
        """GET /v5/market/tickers for the whole category: turnover24h, funding, OI, price."""
        res = self._call("get_tickers", what="tickers", category=self.category)
        return list(res.get("list") or [])

    def last_price(self, symbol: str) -> Decimal:
        res = self._call("get_tickers", what="tickers", category=self.category, symbol=symbol)
        rows = res.get("list") or []
        if not rows or rows[0].get("lastPrice") in (None, ""):
            raise GatewayError("tickers", msg=f"{symbol}: no lastPrice", kind="network")
        return Decimal(str(rows[0]["lastPrice"]))

    def wallet_equity(self) -> Decimal:
        res = self._call("get_wallet_balance", what="wallet", accountType="UNIFIED")
        rows = res.get("list") or []
        if not rows:
            raise GatewayError("wallet", msg="empty list", kind="network")
        total = rows[0].get("totalEquity")
        if total in (None, ""):
            raise GatewayError("wallet", msg="totalEquity missing", kind="network")
        return Decimal(str(total))

    def fee_rate(self, symbol: str) -> tuple[Decimal, Decimal]:
        try:
            res = self._call(
                "get_fee_rates", what="fee_rate", category=self.category, symbol=symbol
            )
        except GatewayError as exc:
            if self.mode == "demo" and exc.code == 10001:
                self.fee_rates[symbol] = DEMO_FEE_FALLBACK
                return DEMO_FEE_FALLBACK
            raise
        rows = res.get("list") or []
        if not rows:
            raise GatewayError("fee_rate", msg="empty list", kind="network")
        pair = Decimal(str(rows[0]["makerFeeRate"])), Decimal(str(rows[0]["takerFeeRate"]))
        self.fee_rates[symbol] = pair
        return pair

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"category": self.category}
        if symbol:
            kwargs["symbol"] = symbol
        else:
            kwargs["settleCoin"] = "USDT"
        res = self._call("get_positions", what="positions", **kwargs)
        return list(res.get("list") or [])

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"category": self.category, "openOnly": 0}
        if symbol:
            kwargs["symbol"] = symbol
        else:
            kwargs["settleCoin"] = "USDT"
        res = self._call("get_open_orders", what="open_orders", **kwargs)
        return list(res.get("list") or [])

    def order_by_link(self, symbol: str, link: str) -> dict[str, Any] | None:
        """Realtime first, then history. None when the venue never saw the link."""
        res = self._call(
            "get_open_orders",
            what="order_by_link",
            category=self.category,
            symbol=symbol,
            orderLinkId=link,
        )
        rows = list(res.get("list") or [])
        if not rows:
            res = self._call(
                "get_order_history",
                what="order_by_link",
                category=self.category,
                symbol=symbol,
                orderLinkId=link,
            )
            rows = list(res.get("list") or [])
        return dict(rows[0]) if rows else None

    # --- writes --------------------------------------------------------------------------
    def set_leverage(self, symbol: str, lev: Decimal) -> None:
        key = f"{symbol}:{lev}"
        if key in self._lev_set:
            return
        try:
            self._call(
                "set_leverage",
                what="set_leverage",
                category=self.category,
                symbol=symbol,
                buyLeverage=str(lev),
                sellLeverage=str(lev),
            )
        except GatewayError as exc:
            # 110043 = leverage not modified: already at this value. Not an error.
            if exc.code != CODE_LEVERAGE_NOT_MODIFIED:
                raise
        self._lev_set.add(key)
        self._record("set_leverage", symbol=symbol, lev=str(lev))

    def send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Queue drain callback: sized desk intent → post-only limit with attached SL.

        Statuses (the drain persists them, the desk acts on them):
          sent      — accepted by the venue (or already there: `duplicate=True`)
          rejected  — refused locally or by the venue with a retCode; idea is free
          unknown   — transport failed after place_order left; resolve by link id
        Never raises into the drain.
        """
        try:
            return self._send(payload)
        except GatewayError as exc:
            self._record(
                "send_failed", error=str(exc), code=exc.code, err_kind=exc.kind,
                symbol=payload.get("symbol"),
            )
            if exc.kind == "network" and exc.what == "place_order":
                return {
                    "status": "unknown",
                    "error": str(exc),
                    "orderLinkId": order_link_id(payload),
                    "symbol": payload.get("symbol"),
                }
            return {"status": "rejected", "reason": exc.msg or str(exc), "code": exc.code}
        except Exception as exc:  # anything else is a local bug: refuse, do not hide
            self._record(
                "send_failed", error=str(exc), err_kind="local", symbol=payload.get("symbol")
            )
            return {"status": "rejected", "reason": f"{type(exc).__name__}: {exc}", "code": None}

    def _send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        symbol = str(payload["symbol"])
        side = str(payload["side"]).lower()
        qty = payload.get("qty")
        if qty in (None, "", "0"):
            raise GatewayError("send", msg="intent not sized", kind="local")
        entry = Decimal(str(payload.get("limit_px", payload.get("entry"))))
        stop = Decimal(str(payload.get("stop_px", payload.get("stop"))))
        if side == "buy" and stop >= entry or side == "sell" and stop <= entry:
            raise GatewayError("send", msg="stop on the wrong side of entry", kind="local")
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
        # A recorded `orderLinkId` (unknown-intent resend) is the identity of
        # this queue row. Recomputing from fields would mint a new id when the
        # first send injected `intent_id` that the queue payload does not keep.
        recorded = str(payload.get("orderLinkId") or "")
        link = recorded or order_link_id(payload)
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
            res = self._call("place_order", what="place_order", **req)
        except GatewayError as exc:
            if exc.code == CODE_DUPLICATE_LINK_ID:
                # orderLinkId already used → this row is already on the venue
                self._record("send_duplicate", symbol=symbol, orderLinkId=link)
                return {"status": "sent", "orderLinkId": link, "duplicate": True, "symbol": symbol}
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

    def resolve_unknown(self, symbol: str, link: str) -> dict[str, Any]:
        """After a transport failure: did the venue take the order?"""
        try:
            row = self.order_by_link(symbol, link)
        except GatewayError as exc:
            return {"status": "unknown", "error": str(exc), "orderLinkId": link}
        if row is None:
            self._record("unknown_resolved", symbol=symbol, orderLinkId=link, outcome="absent")
            return {"status": "rejected", "reason": "not_on_venue", "orderLinkId": link}
        status = str(row.get("orderStatus") or "")
        self._record("unknown_resolved", symbol=symbol, orderLinkId=link, outcome=status)
        if status in {"Rejected", "Cancelled", "Deactivated"}:
            return {"status": "rejected", "reason": status, "orderLinkId": link}
        return {
            "status": "sent",
            "orderId": row.get("orderId"),
            "orderLinkId": link,
            "symbol": symbol,
            "venue_status": status,
        }

    def place_half_tp(
        self, *, symbol: str, side: str, qty: Decimal, price: Decimal, link: str
    ) -> dict[str, Any]:
        """Reduce-only limit for the +1R half (law 1.6.3). `side` is the POSITION side."""
        res = self._call(
            "place_order",
            what="place_half_tp",
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
        )
        self._record("half_tp_sent", symbol=symbol, qty=str(qty), price=str(price))
        return res

    def amend_stop(self, symbol: str, new_stop: Decimal) -> dict[str, Any]:
        res = self._call(
            "set_trading_stop",
            what="amend_stop",
            category=self.category,
            symbol=symbol,
            tpslMode="Full",
            positionIdx=self.position_idx,
            stopLoss=str(new_stop),
            slTriggerBy="MarkPrice",
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
        res = self._call("set_trading_stop", what="set_trailing", **kwargs)
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
        res = self._call("cancel_all_orders", what="cancel_entries", **kwargs)
        self._record(
            "entries_cancelled", symbol=symbol, reason=reason, n=len(res.get("list") or [])
        )
        return res

    def flatten(self, symbol: str, *, reason: str = "flatten") -> dict[str, Any]:
        """Cancel entries, market reduce-only for the whole position, re-read until flat."""
        self.cancel_entries(symbol, reason=reason)
        before = [p for p in self.positions(symbol) if Decimal(str(p.get("size") or "0")) > 0]
        sent: list[dict[str, Any]] = []
        for pos in before:
            side = str(pos.get("side") or "").lower()
            res = self._call(
                "place_order",
                what="flatten",
                category=self.category,
                symbol=symbol,
                side="Sell" if side == "buy" else "Buy",
                orderType="Market",
                qty=str(pos["size"]),
                reduceOnly=True,
                positionIdx=int(pos.get("positionIdx") or self.position_idx),
            )
            sent.append(res)
        after: list[dict[str, Any]] = before
        for i in range(self.settle_reads):
            after = [p for p in self.positions(symbol) if Decimal(str(p.get("size") or "0")) > 0]
            if not after or i == self.settle_reads - 1:
                break
            self._sleep(self.settle_wait_s)
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
    def probe_params(self, symbol: str) -> dict[str, str]:
        """Far-from-market post-only probe that satisfies the instrument filters:
        price = 50% of last rounded to tick; qty ≥ minOrderQty and ≥ minNotional/price."""
        inst = self.instrument(symbol)
        pf = inst.get("priceFilter") or {}
        lf = inst.get("lotSizeFilter") or {}
        tick = Decimal(str(pf.get("tickSize") or "0.1"))
        step = Decimal(str(lf.get("qtyStep") or lf.get("minOrderQty") or "0.001"))
        min_qty = Decimal(str(lf.get("minOrderQty") or step))
        min_notional = Decimal(str(lf.get("minNotionalValue") or "5"))
        last = self.last_price(symbol)
        price = _round_step(last * Decimal("0.5"), tick)
        if price <= 0:
            price = tick
        need = _round_step(min_notional / price, step, up=True)
        qty = max(min_qty, need)
        return {"price": str(price), "qty": str(qty)}

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
                params = self.probe_params(symbol)
                res = self._call(
                    "place_order",
                    what="probe_place",
                    category=self.category,
                    symbol=symbol,
                    side="Buy",
                    orderType="Limit",
                    qty=params["qty"],
                    price=params["price"],
                    timeInForce="PostOnly",
                    orderLinkId=f"hello-{int(self._clock().timestamp())}",
                    positionIdx=self.position_idx,
                )
                self._call(
                    "cancel_order",
                    what="probe_cancel",
                    category=self.category,
                    symbol=symbol,
                    orderId=res.get("orderId"),
                )
                return {"orderId": res.get("orderId"), "cancelled": True, **params}

            step("probe_order", probe)
        steps["ok"] = all(v.get("ok") for k, v in steps.items() if isinstance(v, dict))
        self._record("hello", ok=steps["ok"])
        return steps
