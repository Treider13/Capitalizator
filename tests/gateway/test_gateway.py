"""W4b: Bybit gateway on a fake pybit session; watchdog; tracker; OMS drain; loop.

The fake raises the way pybit 5.17 raises: a non-zero retCode is an
`InvalidRequestError` (status_code = retCode, message), transport failures are
`FailedRequestError`. When pybit is installed the real classes are used, so the
error branches are exercised against the SDK's contract, not a dict fiction.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.gateway import (
    BybitGateway,
    GatewayError,
    Keys,
    PositionTracker,
    Watchdog,
    load_keys,
    order_link_id,
)
from capitalizator.gateway.bybit import from_exception
from capitalizator.gateway.ws import PrivateFeed
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import mark_hello, set_user_mode
from capitalizator.ops.vault import init_vault
from capitalizator.signer.process import (
    drain_oms,
    drain_validated,
    gateway_mode_ok,
    publish_exchange_state,
    serve_gateway_loop,
    serve_loop,
)

try:  # real SDK when present; otherwise stand-ins with the same names/fields
    from pybit.exceptions import FailedRequestError, InvalidRequestError
except ImportError:  # pragma: no cover - CI without the [live] extra

    class InvalidRequestError(Exception):  # type: ignore[no-redef]
        def __init__(self, request, message, status_code, time, resp_headers):
            self.request, self.message, self.status_code = request, message, status_code
            super().__init__(f"{message} (ErrCode: {status_code})")

    class FailedRequestError(Exception):  # type: ignore[no-redef]
        def __init__(self, request, message, status_code, time, resp_headers):
            self.request, self.message, self.status_code = request, message, status_code
            super().__init__(f"{message} (ErrCode: {status_code})")


NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def venue_error(code: int, msg: str) -> InvalidRequestError:
    return InvalidRequestError(request="POST /v5/order/create", message=msg, status_code=code,
                               time=NOW.isoformat(), resp_headers=None)


def transport_error(msg: str = "Read timed out") -> FailedRequestError:
    return FailedRequestError(request="POST /v5/order/create", message=msg, status_code=408,
                              time=NOW.isoformat(), resp_headers=None)


class FakeSession:
    """Mimics pybit.unified_trading.HTTP: v5 envelopes on success, exceptions on error."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.orders: dict[str, dict] = {}
        self.history: dict[str, dict] = {}
        self.positions: list[dict] = []
        self.fail_next: str | None = None
        self.fail_with: BaseException | None = None
        self.equity = "100000"
        self.leverage_set: set[str] = set()
        self.last_price = "65000"

    def _rec(self, name: str, kw: dict) -> None:
        self.calls.append((name, kw))
        if self.fail_next == name:
            self.fail_next = None
            exc = self.fail_with or transport_error(f"{name} boom")
            self.fail_with = None
            raise exc

    def get_server_time(self):
        self._rec("get_server_time", {})
        return {"retCode": 0, "result": {"timeSecond": str(int(NOW.timestamp())),
                                         "timeNano": str(int(NOW.timestamp() * 1e9))}}

    def get_instruments_info(self, **kw):
        self._rec("get_instruments_info", kw)
        row = {"symbol": kw.get("symbol") or "BTCUSDT", "status": "Trading",
               "priceFilter": {"tickSize": "0.1"},
               "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "minNotionalValue": "5"},
               "leverageFilter": {"maxLeverage": "100"}, "fundingInterval": 480}
        return {"retCode": 0, "result": {"list": [row], "nextPageCursor": ""}}

    def get_tickers(self, **kw):
        self._rec("get_tickers", kw)
        return {"retCode": 0, "result": {"list": [{"symbol": kw.get("symbol"), "lastPrice": self.last_price}]}}

    def get_wallet_balance(self, **kw):
        self._rec("get_wallet_balance", kw)
        return {"retCode": 0, "result": {"list": [{"totalEquity": self.equity}]}}

    def get_fee_rates(self, **kw):
        self._rec("get_fee_rates", kw)
        return {"retCode": 0, "result": {"list": [{"makerFeeRate": "0.0002", "takerFeeRate": "0.00055"}]}}

    def get_positions(self, **kw):
        self._rec("get_positions", kw)
        return {"retCode": 0, "result": {"list": list(self.positions)}}

    def get_open_orders(self, **kw):
        self._rec("get_open_orders", kw)
        rows = list(self.orders.values())
        if kw.get("orderLinkId"):
            rows = [r for r in rows if r.get("orderLinkId") == kw["orderLinkId"]]
        return {"retCode": 0, "result": {"list": rows}}

    def get_order_history(self, **kw):
        self._rec("get_order_history", kw)
        rows = list(self.history.values())
        if kw.get("orderLinkId"):
            rows = [r for r in rows if r.get("orderLinkId") == kw["orderLinkId"]]
        return {"retCode": 0, "result": {"list": rows}}

    def set_leverage(self, **kw):
        self._rec("set_leverage", kw)
        key = f"{kw['symbol']}:{kw['buyLeverage']}"
        if key in self.leverage_set:
            # pybit raises for retCode 110043 exactly like any other non-zero code
            raise venue_error(110043, "leverage not modified")
        self.leverage_set.add(key)
        return {"retCode": 0, "result": {}}

    def place_order(self, **kw):
        self._rec("place_order", kw)
        link = kw.get("orderLinkId", "")
        if link in self.orders:
            raise venue_error(110072, "OrderLinkedID is duplicate")
        oid = f"oid-{len(self.orders) + 1}"
        self.orders[link or oid] = {**kw, "orderId": oid, "orderStatus": "New"}
        return {"retCode": 0, "result": {"orderId": oid, "orderLinkId": link}}

    def cancel_order(self, **kw):
        self._rec("cancel_order", kw)
        return {"retCode": 0, "result": {"orderId": kw.get("orderId")}}

    def cancel_all_orders(self, **kw):
        self._rec("cancel_all_orders", kw)
        n = len(self.orders)
        self.orders.clear()
        return {"retCode": 0, "result": {"list": [{}] * n}}

    def set_trading_stop(self, **kw):
        self._rec("set_trading_stop", kw)
        return {"retCode": 0, "result": {}}


def _intent(**over) -> dict:
    base = {
        "symbol": "BTCUSDT", "side": "buy", "qty": "0.3", "entry": "65000", "stop": "64300",
        "tp": "66400", "tag": "bounce", "lev": "3", "touch_id": "t1",
        "valid_until": (NOW + timedelta(minutes=30)).isoformat(),
    }
    base.update(over)
    return base


def _gw(session: FakeSession | None = None, mode: str = "testnet", clock=None) -> BybitGateway:
    return BybitGateway(session or FakeSession(), mode=mode, clock=clock or (lambda: NOW),
                        sleep=lambda _s: None)


# --- keys ---------------------------------------------------------------------------
def test_keys_from_env_and_file(tmp_path: Path) -> None:
    assert load_keys(None, env={}) is None
    k = load_keys(None, env={"BYBIT_API_KEY": "abcd1234", "BYBIT_API_SECRET": "SECRET-zz9"})
    # a missing mode flag is Demo Trading — a paper venue, never live
    assert k is not None and k.mode == "demo" and k.demo and not k.testnet and not k.live
    assert "SECRET-zz9" not in repr(k)
    t = load_keys(None, env={"BYBIT_API_KEY": "abcd1234", "BYBIT_API_SECRET": "SECRET-zz9",
                             "BYBIT_MODE": "testnet"})
    assert t is not None and t.testnet and not t.demo
    with pytest.raises(ValueError):
        Keys(api_key="a", api_secret="b", mode="mainnet")
    vault = init_vault(tmp_path / "v")
    f = vault.secrets / "bybit.json"
    f.write_text(json.dumps({"api_key": "k", "api_secret": "s", "mode": "live_sub"}))
    os.chmod(f, 0o644)
    with pytest.raises(ValueError, match="0600"):
        load_keys(vault, env={})
    os.chmod(f, 0o600)
    got = load_keys(vault, env={})
    assert got is not None and got.mode == "live_sub" and not got.testnet and got.live


# --- pybit exception mapping -----------------------------------------------------------
def test_pybit_exceptions_map_to_gateway_error_with_code_and_kind() -> None:
    venue = from_exception(venue_error(110007, "insufficient available balance"), what="place_order")
    assert venue.code == 110007 and venue.kind == "venue" and "insufficient" in venue.msg
    net = from_exception(transport_error(), what="place_order")
    assert net.kind == "network" and net.what == "place_order"
    other = from_exception(ConnectionResetError("peer"), what="wallet")
    assert other.kind == "network" and "ConnectionResetError" in other.msg


# --- gateway -----------------------------------------------------------------------
def test_send_places_post_only_with_attached_stop_and_leverage() -> None:
    s = FakeSession()
    gw = _gw(s)
    out = gw.send(_intent())
    assert out["status"] == "sent" and out["orderId"] == "oid-1"
    names = [c[0] for c in s.calls]
    assert names == ["set_leverage", "place_order"]
    order = s.calls[1][1]
    assert order["timeInForce"] == "PostOnly" and order["orderType"] == "Limit"
    assert order["stopLoss"] == "64300" and order["slTriggerBy"] == "MarkPrice"
    assert order["side"] == "Buy" and order["qty"] == "0.3" and order["price"] == "65000"
    assert order["orderLinkId"] == order_link_id(_intent()) and len(order["orderLinkId"]) == 32
    # same intent again → venue raises 110072 → reported as sent/duplicate, no second order
    again = gw.send(_intent())
    assert again["status"] == "sent" and again.get("duplicate") is True
    assert len(s.orders) == 1
    # leverage is set once per symbol/lev
    assert [c[0] for c in s.calls].count("set_leverage") == 1


def test_leverage_already_set_on_the_venue_is_not_a_failure() -> None:
    """The venue keeps leverage across restarts: a fresh process meets 110043 on its
    first send. pybit raises it; the gateway must treat it as 'already there'."""
    s = FakeSession()
    s.leverage_set.add("BTCUSDT:3")
    out = _gw(s).send(_intent())
    assert out["status"] == "sent"
    assert [c[0] for c in s.calls] == ["set_leverage", "place_order"]


def test_send_refuses_stale_unsized_and_wrong_side() -> None:
    gw = _gw()
    stale = gw.send(_intent(valid_until=(NOW - timedelta(seconds=1)).isoformat()))
    assert stale["status"] == "rejected" and stale["reason"] == "stale_intent"
    unsized = gw.send(_intent(qty=None))
    assert unsized["status"] == "rejected" and "not sized" in unsized["reason"]
    wrong = gw.send(_intent(stop="65100"))
    assert wrong["status"] == "rejected" and "wrong side" in wrong["reason"]
    assert not any(c[0] == "place_order" for c in gw.s.calls)


def test_venue_refusal_is_rejected_transport_failure_is_unknown() -> None:
    s = FakeSession()
    s.fail_next, s.fail_with = "place_order", venue_error(110094, "order value below min notional")
    gw = _gw(s)
    out = gw.send(_intent())
    assert out["status"] == "rejected" and out["code"] == 110094
    assert gw.log[-1]["kind"] == "send_failed" and gw.log[-1]["err_kind"] == "venue"
    # transport failure AFTER the order left: the venue may hold it → unknown, with the link
    s.fail_next = "place_order"
    out2 = gw.send(_intent(touch_id="t2"))
    assert out2["status"] == "unknown" and out2["orderLinkId"] == order_link_id(_intent(touch_id="t2"))


def test_resolve_unknown_asks_the_venue_by_link() -> None:
    s = FakeSession()
    gw = _gw(s)
    link = order_link_id(_intent())
    assert gw.resolve_unknown("BTCUSDT", link)["status"] == "rejected"  # never reached the venue
    s.orders[link] = {"orderLinkId": link, "orderId": "oid-9", "orderStatus": "New"}
    got = gw.resolve_unknown("BTCUSDT", link)
    assert got["status"] == "sent" and got["orderId"] == "oid-9"
    del s.orders[link]
    s.history[link] = {"orderLinkId": link, "orderId": "oid-9", "orderStatus": "Cancelled"}
    assert gw.resolve_unknown("BTCUSDT", link)["status"] == "rejected"


def test_amend_trailing_half_tp_cancel_and_flatten() -> None:
    s = FakeSession()
    gw = _gw(s)
    gw.amend_stop("BTCUSDT", Decimal("64500"))
    assert s.calls[-1][1]["stopLoss"] == "64500" and s.calls[-1][1]["tpslMode"] == "Full"
    gw.set_trailing("BTCUSDT", Decimal("120"), Decimal("66000"))
    assert s.calls[-1][1]["trailingStop"] == "120" and s.calls[-1][1]["activePrice"] == "66000"
    gw.place_half_tp(symbol="BTCUSDT", side="buy", qty=Decimal("0.15"), price=Decimal("65700"), link="abc")
    half = s.calls[-1][1]
    assert half["reduceOnly"] is True and half["side"] == "Sell" and half["orderLinkId"] == "abc-tp1"
    gw.cancel_entries("BTCUSDT", reason="test")
    assert s.calls[-1][1]["orderFilter"] == "Order"  # TP/SL orders untouched
    s.positions = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "positionIdx": 0}]
    res = gw.flatten("BTCUSDT", reason="operator")
    market = [c for c in s.calls if c[0] == "place_order" and c[1].get("orderType") == "Market"]
    assert market and market[-1][1]["reduceOnly"] is True and market[-1][1]["side"] == "Sell"
    # the fake venue never settles: three re-reads, then honest "partial"
    assert res["status"] == "partial"
    assert [c[0] for c in s.calls].count("get_positions") == 1 + gw.settle_reads
    s.positions = []
    assert gw.flatten("BTCUSDT")["status"] == "flat"


def test_hello_probe_uses_instrument_filters() -> None:
    s = FakeSession()
    gw = _gw(s)
    ok = gw.hello(probe_order=True)
    assert ok["ok"] is True
    assert ok["wallet_equity"]["value"] == "100000"
    probe = ok["probe_order"]["value"]
    assert probe["cancelled"] is True
    # 50% of last (65000 → 32500.0 on tick 0.1); minNotional 5 / 32500 → 0.001 (≥ minOrderQty)
    assert probe["price"] == "32500.0" and probe["qty"] == "0.001"
    placed = next(c[1] for c in s.calls if c[0] == "place_order")
    assert Decimal(placed["qty"]) * Decimal(placed["price"]) >= Decimal("5")
    s2 = FakeSession()
    s2.fail_next = "get_wallet_balance"
    bad = _gw(s2).hello()
    assert bad["ok"] is False and bad["wallet_equity"]["ok"] is False and "boom" in bad["wallet_equity"]["error"]


def test_ret_code_dict_and_raised_error_are_both_gateway_errors() -> None:
    class Dict(FakeSession):
        def get_wallet_balance(self, **kw):  # ignore_codes-style session returns the dict
            return {"retCode": 10003, "retMsg": "API key is invalid"}

    class Raises(FakeSession):
        def get_wallet_balance(self, **kw):
            raise venue_error(10003, "API key is invalid")

    for cls in (Dict, Raises):
        with pytest.raises(GatewayError) as exc:
            _gw(cls()).wallet_equity()
        assert exc.value.code == 10003


def test_mode_pairing_demo_paper_live_live() -> None:
    assert gateway_mode_ok("demo", "demo") and gateway_mode_ok("demo", "testnet")
    assert not gateway_mode_ok("demo", "live_sub")
    assert gateway_mode_ok("live", "live_main") and not gateway_mode_ok("live", "testnet")
    assert not gateway_mode_ok("live", "demo")
    assert not gateway_mode_ok("off", "testnet") and not gateway_mode_ok("off", "demo")


def test_demo_keys_build_demo_hosts_never_mainnet() -> None:
    """pybit routes by flags: demo → api-demo / stream-demo; testnet → api-testnet;
    neither → mainnet. A demo key must never produce a mainnet session."""
    pybit = pytest.importorskip("pybit")
    from pybit import _http_manager

    from capitalizator.gateway.bybit import make_session
    from capitalizator.gateway.ws import make_private_ws

    assert pybit is not None
    demo = make_session(Keys(api_key="k1234567", api_secret="s", mode="demo"))
    assert isinstance(demo, _http_manager._V5HTTPManager)
    assert demo.demo is True and demo.testnet is False
    assert "api-demo" in demo.endpoint and "api-testnet" not in demo.endpoint
    tn = make_session(Keys(api_key="k1234567", api_secret="s", mode="testnet"))
    assert tn.testnet is True and tn.demo is False and "api-testnet" in tn.endpoint
    live = make_session(Keys(api_key="k1234567", api_secret="s", mode="live_sub"))
    assert live.testnet is False and live.demo is False and live.endpoint == "https://api.bybit.com"
    # pybit's private WebSocket connects inside __init__, so the factory is checked
    # against a stand-in that records the flags; pybit maps demo=True to stream-demo.
    from pybit import _websocket_stream as ws_mod

    assert ws_mod.DEMO_SUBDOMAIN_MAINNET == "stream-demo"
    captured: dict = {}

    class FakeWs:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import pybit.unified_trading as ut

    real = ut.WebSocket
    ut.WebSocket = FakeWs  # type: ignore[misc,assignment]
    try:
        make_private_ws(Keys(api_key="k1234567", api_secret="s", mode="demo"))
    finally:
        ut.WebSocket = real  # type: ignore[misc]
    assert captured["demo"] is True and captured["testnet"] is False
    assert captured["channel_type"] == "private"
    with pytest.raises(ValueError):
        _gw(mode="mainnet")


# --- watchdog ----------------------------------------------------------------------
def test_watchdog_fires_once_per_episode_and_again_after_recovery() -> None:
    fired: list[str] = []
    healed: list[str] = []
    wd = Watchdog(dead_man_s=30, cancel_entries=fired.append, on_recover=healed.append)
    assert wd.check(NOW) == []  # not armed: nothing to judge
    wd.beat("desk", NOW)
    wd.beat("ws_private", NOW)
    assert wd.check(NOW + timedelta(seconds=29)) == []
    assert wd.check(NOW + timedelta(seconds=31)) == ["desk", "ws_private"]
    assert fired == ["dead_man:desk,ws_private"]
    wd.check(NOW + timedelta(seconds=40))
    assert len(fired) == 1  # same episode
    wd.beat("desk", NOW + timedelta(seconds=41))
    assert wd.check(NOW + timedelta(seconds=42)) == ["ws_private"]
    assert healed == ["desk"] and len(fired) == 1  # ws_private still in its episode
    # desk goes silent a SECOND time → a second cancel (the old code stayed silent forever)
    assert wd.check(NOW + timedelta(seconds=75)) == ["desk", "ws_private"]
    assert fired[-1] == "dead_man:desk" and len(fired) == 2
    wd.note_clock(local=NOW, exchange=NOW - timedelta(seconds=5))
    assert "clock" in wd.stale(NOW + timedelta(seconds=75))


def test_private_feed_liveness_comes_from_the_socket_not_from_frames() -> None:
    class Ws:
        def __init__(self) -> None:
            self.up = True

        def is_connected(self) -> bool:
            return self.up

        def position_stream(self, cb): ...
        def execution_stream(self, cb): ...
        def order_stream(self, cb): ...
        def wallet_stream(self, cb): ...

    ws = Ws()
    feed = PrivateFeed(PositionTracker(), ws=ws)
    feed.start()
    assert feed.connected() is True and feed.last_frame_at is None
    ws.up = False
    assert feed.connected() is False
    assert PrivateFeed(PositionTracker()).connected() is None


# --- tracker / feed --------------------------------------------------------------------
def test_tracker_open_flat_callbacks_and_reconcile() -> None:
    opened, flat, eq = [], [], []
    tr = PositionTracker(on_open=opened.append, on_flat=flat.append, on_equity=lambda e, t: eq.append(e))
    feed = PrivateFeed(tr)
    feed.enqueue({"topic": "position", "data": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3",
                                                 "avgPrice": "65000", "stopLoss": "64300", "liqPrice": "45000",
                                                 "unrealisedPnl": "12", "updatedTime": str(int(NOW.timestamp() * 1000))}]})
    feed.enqueue({"topic": "execution", "data": [{"symbol": "BTCUSDT", "side": "Buy", "execPrice": "65000",
                                                  "execQty": "0.3", "execFee": "3.9", "orderLinkId": "abc",
                                                  "execTime": str(int(NOW.timestamp() * 1000)), "isMaker": True}]})
    feed.enqueue({"topic": "wallet", "data": [{"totalEquity": "99990"}]})
    feed.enqueue({"topic": "order", "data": [{"orderLinkId": "abc", "orderStatus": "Filled"}]})
    assert feed.drain(now=NOW) == 4
    assert len(opened) == 1 and opened[0].stop_loss == Decimal("64300")
    assert tr.stop_confirmed("BTCUSDT") and tr.open_symbols() == ["BTCUSDT"]
    assert tr.fills[0].is_maker and tr.fills[0].fee == Decimal("3.9")
    assert eq == [Decimal("99990")] and tr.orders["abc"]["orderStatus"] == "Filled"
    # REST says the stop is different → mismatch reported, REST adopted (known position)
    mm = tr.reconcile([{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "avgPrice": "65000",
                        "stopLoss": "64000"}], now=NOW)
    assert mm and mm[0]["field"] == "stop_loss" and mm[0]["rest"] == "64000"
    assert tr.positions["BTCUSDT"].stop_loss == Decimal("64000")
    # flat via WS → on_flat
    feed.apply({"topic": "position", "data": [{"symbol": "BTCUSDT", "side": "", "size": "0"}]}, now=NOW)
    assert len(flat) == 1 and tr.open_symbols() == []


def test_unknown_position_is_never_adopted_silently() -> None:
    tr = PositionTracker()
    rest = [{"symbol": "ETHUSDT", "side": "Sell", "size": "1", "avgPrice": "3000"}]
    mm1 = tr.reconcile(rest, now=NOW)
    assert mm1 and mm1[0]["field"] == "unknown_position" and tr.unknown_symbols() == ["ETHUSDT"]
    assert tr.open_symbols() == []  # not ours
    # the SECOND reconcile still reports it (the old code adopted it after one tick)
    mm2 = tr.reconcile(rest, now=NOW + timedelta(seconds=60))
    assert mm2 and mm2[0]["field"] == "unknown_position"
    assert mm2[0]["since"] == NOW.isoformat()
    # operator acknowledges → adopted on the next reconcile
    assert tr.acknowledge("ETHUSDT") is True
    assert tr.reconcile(rest, now=NOW + timedelta(seconds=120)) == []
    assert tr.open_symbols() == ["ETHUSDT"] and tr.unknown_symbols() == []
    # a position the desk expects is never "unknown"
    tr2 = PositionTracker()
    assert tr2.reconcile([{"symbol": "SOLUSDT", "side": "Buy", "size": "5"}], now=NOW,
                         expected={"SOLUSDT"}) == []


# --- OMS drain + loop ------------------------------------------------------------------
def test_drain_oms_executes_desk_decisions(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    gw = _gw(s)
    kn.enqueue_oms(kind="amend_stop", symbol="BTCUSDT", payload={"stop": "64500", "side": "buy"},
                   created_ts=NOW.isoformat())
    kn.enqueue_oms(kind="half_tp", symbol="BTCUSDT", payload={"qty": "0.15", "price": "65700",
                                                             "side": "buy", "paper_id": "t1:demo"},
                   created_ts=NOW.isoformat())
    kn.enqueue_oms(kind="set_trailing", symbol="BTCUSDT", payload={"distance": "120", "active_price": None},
                   created_ts=NOW.isoformat())
    s.fail_next = "place_order"  # the half-TP order fails on the venue
    out = drain_oms(kn, gw, now=NOW)
    assert [o["status"] for o in out] == ["done", "failed", "done"]
    rows = kn.oms_rows()
    assert {r["status"] for r in rows} == {"done", "failed"}
    failed = next(r for r in rows if r["status"] == "failed")
    assert "boom" in failed["result"]["error"]
    assert kn.pending_oms() == []
    kn.close()


def _run_loop(kn, vault, gw, tr, *, now, iterations: int) -> None:
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > iterations

    serve_gateway_loop(knowledge=kn, vault=vault, gateway=gw, tracker=tr, feed=None,
                       should_stop=stop, idle_s=0, now=now)


def test_gateway_loop_block_is_sticky_until_operator_release(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    s = FakeSession()
    gw = _gw(s)
    tr = PositionTracker()
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    kn.set_meta("desk_heartbeat", NOW.isoformat())
    # venue reports a position we do not know → sticky block, intent stays pending
    s.positions = [{"symbol": "ETHUSDT", "side": "Sell", "size": "1", "avgPrice": "3000", "stopLoss": "3100"}]
    _run_loop(kn, vault, gw, tr, now=NOW, iterations=3)  # 3 iterations, 1 reconcile
    blocked = json.loads(kn.meta("entries_blocked"))
    assert "reconcile_mismatch" in blocked and "unknown_position:ETHUSDT" in blocked
    assert kn.pending_intents() and not any(c[0] == "place_order" for c in s.calls)
    state = json.loads(kn.meta("exchange_state"))
    assert state["equity"] == "100000" and state["unknown_positions"] == ["ETHUSDT"]
    # venue flat again and 61s later: the block STAYS (the old one lasted one iteration)
    s.positions = [{"symbol": "ETHUSDT", "side": "", "size": "0"}]
    later = NOW + timedelta(seconds=61)
    kn.set_meta("desk_heartbeat", later.isoformat())
    _run_loop(kn, vault, gw, tr, now=later, iterations=2)
    assert "reconcile_mismatch" in json.loads(kn.meta("entries_blocked"))
    assert kn.pending_intents() and not any(c[0] == "place_order" for c in s.calls)
    # operator release → drained
    kn.enqueue_command("release_signer", {"reason": "checked on the venue"}, created_ts=later.isoformat())
    _run_loop(kn, vault, gw, tr, now=later, iterations=2)
    assert json.loads(kn.meta("entries_blocked")) == []
    assert kn.pending_intents() == []
    assert any(c[0] == "place_order" for c in s.calls)
    orders = kn.order_rows()
    assert orders and orders[0]["status"] == "accepted" and orders[0]["payload"]["orderLinkId"]
    cmds = kn.commands()
    assert cmds[0]["kind"] == "release_signer" and cmds[0]["status"] == "done"
    kn.close()


def test_gateway_loop_resolves_unknown_intents_by_link(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    s = FakeSession()
    gw = _gw(s)
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    kn.set_meta("desk_heartbeat", NOW.isoformat())
    s.fail_next = "place_order"  # transport dies after the order left
    _run_loop(kn, vault, gw, PositionTracker(), now=NOW, iterations=1)
    unknown = kn.intents_with_status("unknown")
    assert len(unknown) == 1 and unknown[0]["result"]["orderLinkId"]
    assert kn.pending_intents() == []
    # the venue actually took it: next reconcile resolves it to sent + order row
    link = unknown[0]["result"]["orderLinkId"]
    s.orders[link] = {"orderLinkId": link, "orderId": "oid-77", "orderStatus": "New", "symbol": "BTCUSDT"}
    later = NOW + timedelta(seconds=61)
    kn.set_meta("desk_heartbeat", later.isoformat())
    _run_loop(kn, vault, gw, PositionTracker(), now=later, iterations=1)
    assert kn.intents_with_status("unknown") == []
    assert kn.intents_with_status("sent")[0]["result"]["orderId"] == "oid-77"
    assert kn.order_rows()[0]["payload"]["orderId"] == "oid-77"
    kn.close()


def test_loop_never_sends_demo_to_a_live_key(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    s = FakeSession()
    gw = _gw(s, mode="live_main")
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    _run_loop(kn, vault, gw, PositionTracker(), now=NOW, iterations=1)
    assert kn.pending_intents()  # untouched
    assert not any(c[0] == "place_order" for c in s.calls)
    kn.close()


def test_drain_validated_keeps_gateway_fields(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    seen: list[dict] = []
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    drain_validated(kn, lambda p: (seen.append(p), {"status": "sent"})[1], user_mode="demo", now=NOW)
    assert seen and seen[0]["valid_until"] and seen[0]["lev"] == "3" and seen[0]["touch_id"] == "t1"
    kn.close()


def test_gateway_loop_publishes_instruments_for_the_desk(tmp_path: Path) -> None:
    from capitalizator.signer.process import publish_instruments

    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)

    class WithInstruments(FakeSession):
        def get_instruments_info(self, **kw):
            self._rec("get_instruments_info", kw)
            return {"retCode": 0, "result": {"list": [
                {"symbol": "DOGEUSDT", "status": "Trading",
                 "priceFilter": {"tickSize": "0.00001"},
                 "lotSizeFilter": {"qtyStep": "1", "minOrderQty": "1", "minNotionalValue": "5"},
                 "leverageFilter": {"maxLeverage": "75"}, "fundingInterval": 480},
                {"symbol": "BROKEN"},
            ], "nextPageCursor": ""}}

    n = publish_instruments(kn, _gw(WithInstruments()), now=NOW)
    assert n == 1
    snap = json.loads(kn.meta("instruments_snapshot"))
    assert snap["instruments"]["DOGEUSDT"]["tick"] == "0.00001" and snap["fetched_at"] == NOW.isoformat()
    # the loop publishes on its first pass and survives a venue error
    set_user_mode(vault, "off", ack=True)
    bad = FakeSession()
    bad.fail_next = "get_instruments_info"
    _run_loop(kn, vault, _gw(bad), PositionTracker(), now=NOW, iterations=1)
    assert kn.meta("instruments_error_signer") == "GatewayError 408"  # type + code, never the text
    kn.close()


def test_no_key_loop_parks_intents_as_no_gateway_and_requeues_later(tmp_path: Path) -> None:
    """Without a key nothing can be sent — and nothing pretends the venue refused."""
    from capitalizator.signer.process import requeue_no_gateway

    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    mark_hello(vault, ok=True)
    set_user_mode(vault, "demo", ack=True)
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    kn.set_meta("desk_heartbeat", (NOW - timedelta(seconds=120)).isoformat())  # desk silent
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 1

    serve_loop(knowledge=kn, vault=vault, should_stop=stop, idle_s=0, now=NOW)
    assert kn.pending_intents() == []
    parked = kn.intents_with_status("no_gateway")
    assert len(parked) == 1 and kn.intent_status(parked[0]["id"]) == "no_gateway"
    assert json.loads(kn.meta("entries_blocked")) == ["desk", "no_gateway"]
    assert kn.intents_with_status("failed") == []  # the desk keeps its idea
    # a gateway appears → the row is pending again
    assert requeue_no_gateway(kn) == 1 and len(kn.pending_intents()) == 1
    kn.close()


def test_identical_intents_on_two_days_get_distinct_order_link_ids(tmp_path: Path) -> None:
    """Without the queue id both intents hashed alike → venue 'duplicate' → fake 'sent'."""
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    gw = _gw(s)
    same = {k: v for k, v in _intent().items() if k != "touch_id"}
    kn.enqueue_intent(same, created_ts=NOW.isoformat())
    kn.enqueue_intent(same, created_ts=(NOW + timedelta(days=1)).isoformat())
    drain_validated(kn, gw.send, user_mode="demo", now=NOW)
    placed = [c[1]["orderLinkId"] for c in s.calls if c[0] == "place_order"]
    assert len(placed) == 2 and placed[0] != placed[1]
    assert len(s.orders) == 2
    assert not any(r["kind"] == "send_duplicate" for r in gw.log)
    kn.close()


def test_publish_exchange_state_reports_missing_stop_and_fills(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    s.positions = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "avgPrice": "65000", "stopLoss": ""}]
    tr = PositionTracker()
    tr.on_execution([{"symbol": "BTCUSDT", "side": "Buy", "execPrice": "65000", "execQty": "0.3",
                      "execFee": "3.9", "orderLinkId": "abc", "isMaker": True}])
    kn.set_meta("account", json.dumps({"open": [{"symbol": "BTCUSDT"}]}))  # the desk's idea
    state = publish_exchange_state(kn, _gw(s), tr, now=NOW)
    assert state["stop_missing"] == ["BTCUSDT"]
    assert state["fills"][0]["orderLinkId"] == "abc"
    kn.close()
