"""W4b: Bybit gateway on a fake pybit session; watchdog; tracker; OMS drain; loop."""

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
from capitalizator.gateway.ws import PrivateFeed
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.product import set_user_mode
from capitalizator.ops.vault import init_vault
from capitalizator.signer.process import (
    drain_oms,
    drain_validated,
    gateway_mode_ok,
    publish_exchange_state,
    serve_gateway_loop,
)

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


class FakeSession:
    """Mimics pybit.unified_trading.HTTP with documented v5 response envelopes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.orders: dict[str, dict] = {}
        self.positions: list[dict] = []
        self.fail_next: str | None = None
        self.equity = "100000"

    def _rec(self, name: str, kw: dict) -> None:
        self.calls.append((name, kw))
        if self.fail_next == name:
            self.fail_next = None
            raise RuntimeError(f"{name} boom")

    def get_server_time(self):
        self._rec("get_server_time", {})
        return {"retCode": 0, "result": {"timeSecond": str(int(NOW.timestamp())), "timeNano": str(int(NOW.timestamp() * 1e9))}}

    def get_instruments_info(self, **kw):
        self._rec("get_instruments_info", kw)
        return {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": ""}}

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
        return {"retCode": 0, "result": {"list": list(self.orders.values())}}

    def set_leverage(self, **kw):
        self._rec("set_leverage", kw)
        return {"retCode": 0, "result": {}}

    def place_order(self, **kw):
        self._rec("place_order", kw)
        link = kw.get("orderLinkId", "")
        if link in self.orders:
            return {"retCode": 110072, "retMsg": "OrderLinkedID is duplicate"}
        oid = f"oid-{len(self.orders) + 1}"
        self.orders[link or oid] = {**kw, "orderId": oid}
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
    return BybitGateway(session or FakeSession(), mode=mode, clock=clock or (lambda: NOW))


# --- keys ---------------------------------------------------------------------------
def test_keys_from_env_and_file(tmp_path: Path) -> None:
    assert load_keys(None, env={}) is None
    k = load_keys(None, env={"BYBIT_API_KEY": "abcd1234", "BYBIT_API_SECRET": "SECRET-zz9"})
    assert k is not None and k.mode == "testnet" and k.testnet
    assert "SECRET-zz9" not in repr(k)
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
    assert got is not None and got.mode == "live_sub" and not got.testnet


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
    # same intent again → venue says duplicate → reported as sent, no second order
    again = gw.send(_intent())
    assert again["status"] == "sent" and again.get("duplicate") is True
    assert len(s.orders) == 1
    # leverage is set once per symbol/lev
    assert [c[0] for c in s.calls].count("set_leverage") == 1


def test_send_refuses_stale_unsized_and_wrong_side() -> None:
    gw = _gw()
    stale = gw.send(_intent(valid_until=(NOW - timedelta(seconds=1)).isoformat()))
    assert stale["status"] == "rejected" and stale["reason"] == "stale_intent"
    assert gw.send(_intent(qty=None))["status"] == "failed"
    assert gw.send(_intent(stop="65100"))["status"] == "failed"
    assert not any(c[0] == "place_order" for c in gw.s.calls)


def test_send_surfaces_venue_errors_without_raising() -> None:
    s = FakeSession()
    s.fail_next = "place_order"
    gw = _gw(s)
    out = gw.send(_intent())
    assert out["status"] == "failed" and "boom" in out["error"]
    assert gw.log[-1]["kind"] == "send_failed"


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
    assert res["status"] == "partial"  # fake venue still reports the position; loop re-reads
    s.positions = []
    assert gw.flatten("BTCUSDT")["status"] == "flat"


def test_hello_reports_each_step() -> None:
    s = FakeSession()
    gw = _gw(s)
    ok = gw.hello(probe_order=True)
    assert ok["ok"] is True
    assert ok["wallet_equity"]["value"] == "100000"
    assert ok["probe_order"]["value"]["cancelled"] is True
    s2 = FakeSession()
    s2.fail_next = "get_wallet_balance"
    bad = _gw(s2).hello()
    assert bad["ok"] is False and bad["wallet_equity"]["ok"] is False and "boom" in bad["wallet_equity"]["error"]


def test_ret_code_error_is_gateway_error() -> None:
    class Bad(FakeSession):
        def get_wallet_balance(self, **kw):
            return {"retCode": 10003, "retMsg": "API key is invalid"}

    with pytest.raises(GatewayError, match="10003"):
        _gw(Bad()).wallet_equity()


def test_mode_pairing_demo_testnet_live_live() -> None:
    assert gateway_mode_ok("demo", "testnet") and not gateway_mode_ok("demo", "live_sub")
    assert gateway_mode_ok("live", "live_main") and not gateway_mode_ok("live", "testnet")
    assert not gateway_mode_ok("off", "testnet")
    with pytest.raises(ValueError):
        _gw(mode="mainnet")


# --- watchdog ----------------------------------------------------------------------
def test_watchdog_fires_once_per_stale_episode_and_never_before_a_beat() -> None:
    fired: list[str] = []
    wd = Watchdog(dead_man_s=30, cancel_entries=fired.append)
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
    assert fired[-1] == "dead_man:ws_private"
    wd.note_clock(local=NOW, exchange=NOW - timedelta(seconds=5))
    assert "clock" in wd.stale(NOW + timedelta(seconds=42))


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
    # REST says the stop is different → mismatch reported, REST adopted
    mm = tr.reconcile([{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "avgPrice": "65000",
                        "stopLoss": "64000"}], now=NOW)
    assert mm and mm[0]["field"] == "stop_loss" and mm[0]["rest"] == "64000"
    assert tr.positions["BTCUSDT"].stop_loss == Decimal("64000")
    # flat via WS → on_flat
    feed.apply({"topic": "position", "data": [{"symbol": "BTCUSDT", "side": "", "size": "0"}]}, now=NOW)
    assert len(flat) == 1 and tr.open_symbols() == []
    # REST shows a position we never saw → CRITICAL mismatch; an expected (desk) one is fine
    mm2 = tr.reconcile([{"symbol": "ETHUSDT", "side": "Sell", "size": "1", "avgPrice": "3000"}], now=NOW)
    assert mm2 and mm2[0]["symbol"] == "ETHUSDT" and mm2[0]["field"] == "unknown_position"
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


def test_gateway_loop_blocks_entries_on_mismatch_and_drains_when_clean(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    set_user_mode(vault, "demo", ack=True)
    s = FakeSession()
    gw = _gw(s)
    tr = PositionTracker()
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    kn.set_meta("desk_heartbeat", NOW.isoformat())
    # venue reports a position we do not know → mismatch → entries blocked, intent stays pending
    s.positions = [{"symbol": "ETHUSDT", "side": "Sell", "size": "1", "avgPrice": "3000", "stopLoss": "3100"}]
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 1

    serve_gateway_loop(knowledge=kn, vault=vault, gateway=gw, tracker=tr, feed=None,
                       should_stop=stop, idle_s=0, now=NOW)
    assert json.loads(kn.meta("entries_blocked")) == ["reconcile_mismatch"]
    assert kn.pending_intents() and not any(c[0] == "place_order" for c in s.calls)
    state = json.loads(kn.meta("exchange_state"))
    assert state["equity"] == "100000" and state["positions"][0]["symbol"] == "ETHUSDT"
    assert state["mismatches"][0]["field"] == "unknown_position"
    # venue flat again, desk heartbeat fresh → drained
    s.positions = [{"symbol": "ETHUSDT", "side": "", "size": "0"}]
    later = NOW + timedelta(seconds=61)
    kn.set_meta("desk_heartbeat", later.isoformat())
    ticks["n"] = 0
    serve_gateway_loop(knowledge=kn, vault=vault, gateway=gw, tracker=tr, feed=None,
                       should_stop=stop, idle_s=0, now=later)
    assert json.loads(kn.meta("entries_blocked")) == []
    assert kn.pending_intents() == []
    assert any(c[0] == "place_order" for c in s.calls)
    orders = kn.order_rows()
    assert orders and orders[0]["status"] == "accepted" and orders[0]["payload"]["orderLinkId"]
    kn.close()


def test_loop_never_sends_demo_to_a_live_key(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    set_user_mode(vault, "demo", ack=True)
    s = FakeSession()
    gw = _gw(s, mode="live_main")
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    n = {"n": 0}

    def stop() -> bool:
        n["n"] += 1
        return n["n"] > 1

    serve_gateway_loop(knowledge=kn, vault=vault, gateway=gw, tracker=PositionTracker(), feed=None,
                       should_stop=stop, idle_s=0, now=NOW)
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
    n2 = {"n": 0}

    def stop() -> bool:
        n2["n"] += 1
        return n2["n"] > 1

    serve_gateway_loop(knowledge=kn, vault=vault, gateway=_gw(bad), tracker=PositionTracker(), feed=None,
                       should_stop=stop, idle_s=0, now=NOW)
    assert "boom" in kn.meta("instruments_error")
    kn.close()


def test_legacy_no_key_loop_watches_the_desk_heartbeat(tmp_path: Path) -> None:
    """Н-4: the old DeadMan beat itself. The no-key loop now reads the desk heartbeat."""
    from capitalizator.signer.process import serve_loop

    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    set_user_mode(vault, "demo", ack=True)
    kn.enqueue_intent(_intent(), created_ts=NOW.isoformat())
    cancels: list[int] = []
    sent: list[dict] = []
    kn.set_meta("desk_heartbeat", (NOW - timedelta(seconds=120)).isoformat())  # desk silent
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 1

    serve_loop(knowledge=kn, vault=vault, send=lambda p: (sent.append(p), {"status": "sent"})[1],
               cancel_all=lambda: cancels.append(1), should_stop=stop, idle_s=0, now=NOW)
    assert cancels == [1] and sent == [] and kn.pending_intents()
    assert json.loads(kn.meta("entries_blocked")) == ["desk"]
    kn.set_meta("desk_heartbeat", NOW.isoformat())
    ticks["n"] = 0
    serve_loop(knowledge=kn, vault=vault, send=lambda p: (sent.append(p), {"status": "sent"})[1],
               cancel_all=lambda: cancels.append(1), should_stop=stop, idle_s=0, now=NOW)
    assert sent and kn.pending_intents() == [] and json.loads(kn.meta("entries_blocked")) == []
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


def test_publish_exchange_state_reports_missing_stop(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    s = FakeSession()
    s.positions = [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.3", "avgPrice": "65000", "stopLoss": ""}]
    state = publish_exchange_state(kn, _gw(s), PositionTracker(), now=NOW)
    assert state["stop_missing"] == ["BTCUSDT"]
    kn.close()
