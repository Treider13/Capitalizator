"""Dual-book mechanics with controlled feeds; no claims about trading returns."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from tests.fusion.test_contract_runtime import account, block, contract, instrument, register
from tests.fusion.test_review import Socket

from capitalizator.fusion.config import Config
from capitalizator.fusion.cross_market import SpotBook, entry_check
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.market import Market
from capitalizator.fusion.public import RawPublic
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store


def frame(symbol="BTCUSDT", *, bid=100, qty=2, at=101, generation=1, u=10, kind="snapshot"):
    return {
        "topic": "orderbook.50." + symbol,
        "generation": generation,
        "type": kind,
        "ts": at * 1000,
        "data": {"s": symbol, "u": u, "b": [[str(bid), str(qty)]], "a": [[str(bid * 1.0002), "1"]]},
    }


@pytest.mark.parametrize("symbol,price", zip(Config().symbols, [60000, 2500, 3000, 150, 600, 0.1]))
def test_six_pairs_books_stay_separate_and_basis_uses_same_asset(symbol, price):
    m = Market(symbol, Config())
    m.ingest("book", frame(symbol, bid=price * 1.001), 101)
    original = (dict(m.bids), dict(m.asks), m.refill)
    m.ingest("spot_book", frame(symbol, bid=price), 101)
    cross = m.cross_market()
    assert cross["basis_bps"] == pytest.approx(10)
    assert cross["spot"]["symbol"] == symbol
    assert cross["spot"]["bid_notional"] == pytest.approx(price * 2)
    assert entry_check(cross, 1, 101, m.config) == "ready"
    assert entry_check(cross, -1, 101, m.config) == "spot_pressure_opposes_entry"
    m.ingest("spot_book", frame(symbol, bid=price, qty=3, u=11, kind="delta"), 101)
    assert (m.bids, m.asks, m.refill) == original
    assert not m.blocks and not m.pending and not m.hist  # No fabricated futures prints.


def test_spot_delta_deletion_reset_duplicates_and_old_generation():
    b = SpotBook("BTCUSDT")
    b.ingest("spot_book", frame(u=12, kind="delta"), 101)
    assert not b.snapshot()["valid"]
    b.ingest("spot_book", frame(), 101)
    delta = frame(bid=99, u=11, kind="delta")
    delta["data"]["b"].append(["100", "0"])
    b.ingest("spot_book", delta, 102)
    assert b.bids == {99: 2}
    b.ingest("spot_book", frame(qty=99, u=10, kind="delta"), 103)
    assert b.at == 102 and b.bids == {99: 2}
    b.ingest("spot_status", {"generation": 2, "status": "reconnecting"}, 103)
    b.ingest("spot_book", frame(), 104)
    assert b.generation == 2 and not b.snapshot()["valid"]
    b.ingest("spot_book", frame(generation=2, u=1, kind="delta"), 105)
    assert b.bids == {100: 2}  # Venue u=1 is a replacement snapshot.


@pytest.mark.parametrize("mutation", ["wrong_symbol", "negative", "nan", "crossed", "old_time"])
def test_invalid_spot_frames_cannot_be_used(mutation):
    b = SpotBook("BTCUSDT")
    b.ingest("spot_book", frame(), 101)
    bad = frame(u=11, kind="delta")
    if mutation == "wrong_symbol":
        bad["data"]["s"] = "ETHUSDT"
    elif mutation == "negative":
        bad["data"]["b"][0][1] = "-1"
    elif mutation == "nan":
        bad["data"]["b"][0][0] = "nan"
    elif mutation == "crossed":
        bad["data"]["b"][0][0] = "101"
    else:
        bad["ts"] = 100000
    with pytest.raises(ValueError):
        b.ingest("spot_book", bad, 102)
    assert not b.snapshot()["valid"]


def test_stale_exchange_data_is_not_refreshed_by_late_receipt():
    m = Market("BTCUSDT", Config())
    m.ingest("book", frame(), 110)
    m.ingest("spot_book", frame(), 110)
    assert entry_check(m.cross_market(), 1, 110, m.config) == "spot_stale"
    m.ingest("spot_book", frame(at=110), 110)
    assert entry_check(m.cross_market(), 1, 110, m.config) == "ready"
    assert entry_check(m.cross_market(), 1, 116, m.config) == "spot_stale"
    assert entry_check(m.cross_market(), 1, 109, m.config) == "spot_stale"


def test_opposing_futures_book_and_wide_spot_spread_veto_entry():
    m = Market("BTCUSDT", Config())
    m.ingest("book", frame(qty=0.5), 101)
    m.ingest("spot_book", frame(), 101)
    assert m.cross_market()["opposed"] is True
    assert entry_check(m.cross_market(), 1, 101, m.config) == "linear_pressure_opposes_entry"
    wide = frame()
    wide["data"]["a"] = [["110", "1"]]
    m.ingest("spot_book", wide, 101)
    assert entry_check(m.cross_market(), 1, 101, m.config) == "spot_spread_wide"


@pytest.mark.parametrize("spot_qty,orders", [(2, 1), (0.5, 0)])
def test_production_reservation_consumes_both_books(tmp_path, spot_qty, orders):
    store = Store(tmp_path / "db")
    try:
        cfg = Config()
        engine = Engine("BTCUSDT", store, Shared(), cfg, variant="B")
        engine.contract = contract()
        register(store, engine.contract)
        account(store)
        engine.market.ingest("book", frame(qty=2000), 101)
        engine.market.ingest("ticker", {"data": {}}, 101)
        engine.market.ingest("spot_book", frame(qty=spot_qty), 101)
        engine._reserve_entry(block(), None, instrument(), "demo", True, 0.001)
        assert len(store.rows("SELECT * FROM orders")) == orders
        if not orders:
            assert (
                "spot_pressure_opposes_entry"
                in store.rows("SELECT body FROM decisions")[-1]["body"]
            )
    finally:
        store.close()


def test_dispatch_rechecks_generation_and_direction_using_stored_order_body(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, Config())
    try:
        c = contract()
        register(runtime.store, c)
        runtime.shared.broker_ready = True
        runtime.shared.news_required = False
        runtime.executor = SimpleNamespace(last_reconcile=101)
        engine = runtime.engines["BTCUSDT"]
        engine.market.ingest("book", frame(), 101)
        engine.market.ingest("ticker", {"data": {}}, 101)
        engine.market.ingest("spot_book", frame(), 101)
        runtime.spot_generations["BTCUSDT"] = 1
        runtime.shared.snapshots["BTCUSDT"] = engine.market.snapshot()
        monkeypatch.setattr("capitalizator.fusion.runtime.time.time", lambda: 101)
        order = {
            "symbol": "BTCUSDT",
            "mode": "demo",
            "contract": c.id,
            "expires": 110,
            "body": json.dumps({"side": "Buy"}),
        }
        assert runtime._authorize_send(order)
        assert not runtime._authorize_send({**order, "body": json.dumps({"side": "Sell"})})
        runtime._spot_status("BTCUSDT", "reconnecting")
        assert not runtime._authorize_send(order)  # Even BEFORE actor drains status event.
    finally:
        runtime.store.close()


def test_spot_callback_filters_old_generation_and_old_futures_epoch(tmp_path):
    r = Runtime(tmp_path, Config())
    try:
        generation, epoch = r._spot_status("BTCUSDT", "awaiting_snapshot")
        mailbox = r.mailboxes[r.routes["BTCUSDT"]]
        mailbox.get(0)
        r._spot_event("BTCUSDT", "spot_book", frame(), generation - 1, epoch)
        r._spot_event("BTCUSDT", "spot_book", frame(), generation, epoch - 1)
        assert not mailbox.get(0)
        r._spot_event("BTCUSDT", "spot_book", frame(), generation, epoch)
        assert mailbox.get(0)[0][1] == "spot_book"
    finally:
        r.store.close()


def test_spot_wire_uses_spot_endpoint_without_derivative_topics():
    urls = []

    def factory(url, **kwargs):
        urls.append(url)
        return Socket(url, **kwargs)

    wire = RawPublic(("BTCUSDT",), lambda _: None, factory=factory, category="spot")
    try:
        assert wire.ws.ready.wait(1)
        assert urls == ["wss://stream.bybit.com/v5/public/spot"]
        assert wire.ws.sent[0]["args"] == ["orderbook.50.BTCUSDT"]
    finally:
        wire.exit()


def test_unavailable_gold_never_substitutes_tokenized_gold(tmp_path, monkeypatch):
    r = Runtime(tmp_path, Config())
    calls = []

    def get(path, params, timeout):
        calls.append(params)
        r.supervisor.stop.set()
        return {
            "list": [
                {"symbol": "PAXGUSDT", "baseCoin": "PAXG", "quoteCoin": "USDT", "status": "Trading"}
            ]
        }

    monkeypatch.setattr("capitalizator.fusion.runtime.public_get", get)
    monkeypatch.setattr(
        "capitalizator.fusion.public.RawPublic",
        lambda *a, **kw: pytest.fail("must not subscribe an unmatched asset"),
    )
    try:
        r._spot_worker("XAUUSDT")
        items = r.mailboxes[r.routes["XAUUSDT"]].get(0)
        assert any(item[2].get("status") == "instrument_unavailable" for item in items)
        assert calls == [{"category": "spot", "symbol": "XAUUSDT"}]
    finally:
        r.store.close()


def test_slow_spot_discovery_does_not_block_another_pair(tmp_path, monkeypatch):
    r = Runtime(tmp_path, Config())
    entered, release, other = threading.Event(), threading.Event(), threading.Event()

    def get(path, params, timeout):
        if params["symbol"] == "BTCUSDT":
            entered.set()
            assert release.wait(3)
        else:
            other.set()
        return {"list": []}

    monkeypatch.setattr("capitalizator.fusion.runtime.public_get", get)
    first = threading.Thread(target=r._spot_worker, args=("BTCUSDT",))
    second = threading.Thread(target=r._spot_worker, args=("ETHUSDT",))
    try:
        first.start()
        assert entered.wait(1)
        second.start()
        assert other.wait(1)
    finally:
        r.supervisor.stop.set()
        release.set()
        first.join(3)
        second.join(3)
        assert not first.is_alive() and not second.is_alive()
        r.store.close()


def test_actor_recovers_spot_without_resetting_futures_and_rejects_old_socket(
    tmp_path, monkeypatch
):
    r = Runtime(tmp_path, Config())
    wires = []
    stop_wait = threading.Event()

    def eventually(predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if predicate():
                return
            stop_wait.wait(0.01)
        pytest.fail("market transition did not complete")

    def factory(symbols, callback, **kwargs):
        wire = RawPublic(symbols, callback, factory=Socket, **kwargs)
        wires.append(wire)
        return wire

    monkeypatch.setattr("capitalizator.fusion.public.RawPublic", factory)
    monkeypatch.setattr(
        "capitalizator.fusion.runtime.public_get",
        lambda *args: {
            "list": [
                {"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "status": "Trading"}
            ]
        },
    )
    symbol = "BTCUSDT"

    def snap():
        with r.shared.lock:
            return r.shared.snapshots.get(symbol, {})

    try:
        r.supervisor.start("market-0", lambda: r._market_worker(0))
        r.supervisor.start("spot-BTCUSDT", lambda: r._spot_worker(symbol))
        r.callback(frame(at=time.time()))
        eventually(lambda: snap().get("valid") and len(wires) == 1)
        wires[0]._message(wires[0].ws, json.dumps(frame(at=time.time())))
        eventually(lambda: snap().get("cross_market", {}).get("spot", {}).get("valid"))
        before = snap()["book_levels"]
        bad = frame(at=time.time(), u=11, kind="delta")
        bad["data"]["b"][0][1] = "-1"
        wires[0]._message(wires[0].ws, json.dumps(bad))
        eventually(lambda: len(wires) == 2)
        assert snap()["valid"] and snap()["book_levels"] == before
        assert not r.shared.halted
        assert not snap()["cross_market"]["spot"]["valid"]
        pending = r.mailboxes[0].status()["pending"]
        wires[0]._message(wires[0].ws, json.dumps(frame(qty=999, at=time.time())))
        assert r.mailboxes[0].status()["pending"] <= pending  # Old callback not enqueued.
        wires[1]._message(wires[1].ws, json.dumps(frame(qty=3, at=time.time())))
        eventually(lambda: snap()["cross_market"]["spot"].get("bid_notional") == 300)
        assert snap()["book_levels"] == before
        recorded = r.store.rows("SELECT kind FROM events WHERE symbol=?", (symbol,))
        assert {"spot_status", "spot_book", "book"} <= {row["kind"] for row in recorded}
    finally:
        r.close()
    assert all(not wire.thread.is_alive() and not wire.heartbeat.is_alive() for wire in wires)
    assert not r.shared.halted  # Normal shutdown is not a queue overflow.
