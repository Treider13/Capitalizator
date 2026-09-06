from __future__ import annotations

import json
import threading
from dataclasses import replace

import numpy as np
import pytest

from capitalizator.fusion.atlas import Forecast, train
from capitalizator.fusion.concurrency import FairLock, Mailbox
from capitalizator.fusion.config import Config
from capitalizator.fusion.contracts import Contract
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.market import Block, Market, profile
from capitalizator.fusion.risk import Instrument, reserve
from capitalizator.fusion.store import Store, encode


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "ledger.sqlite")
    yield s
    s.close()


@pytest.fixture
def config():
    return Config(
        symbols=("BTCUSDT", "ETHUSDT"),
        context_blocks=4,
        block_trades=2,
        block_seconds=0.001,
        horizon_blocks=2,
        demo_samples=32,
        live_samples=128,
        retrain_samples=16,
        risk_fraction=0.005,
        max_positions=8,
    )


def contract(symbol="BTCUSDT", ident="c1", at=100.0):
    return Contract(
        ident,
        symbol,
        1,
        at,
        1,
        2,
        5,
        at + 120,
        "model",
        "config",
        100,
        95,
        120,
        0.1,
        -0.1,
        0.01,
        (0.0,) * 12,
        {},
    )


def block(ident=2, at=101.0, **overrides):
    values = dict(
        id=ident,
        at=at,
        start=at - 1,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=100.0,
        flow=0.5,
        refill=0.2,
        x=(0.0,) * 12,
        context={
            "sweep": 1,
            "discount": 0.25,
            "support": 95,
            "resistance": 120,
            "sweep_extreme": 94,
            "atr": 1.0,
            "ask": 101.0,
            "bid": 100.0,
            "depth": 1000.0,
            "funding": 0.0,
        },
    )
    values.update(overrides)
    return Block(**values)


def register(store, c, state="confirmed"):
    with store.transaction() as db:
        db.execute(
            "INSERT INTO contracts VALUES(?,?,?,?,?,?)",
            (c.id, c.symbol, c.created, state, encode(c.payload()), c.created),
        )


def instrument(symbol="BTCUSDT"):
    return Instrument(symbol, 0.01, 0.001, 0.001, 1.0, 10000.0, 10.0, 0.0002, 0.00055, 480)


def account(store, at=101, equity=10000, positions=None):
    store.account("demo", at, equity, positions or [], [], "2026-09-06")


def test_contract_only_uses_future_fixed_checkpoint():
    c = contract()
    assert c.evaluate(block(at=100))[0] == "observing"
    assert c.evaluate(block(ident=1))[0] == "observing"
    assert c.evaluate(block())[0] == "confirmed"
    assert c.evaluate(block(flow=-0.2))[0] == "refuted"
    assert c.evaluate(block(low=94))[1] == "invalidation_traded"
    assert c.evaluate(block(at=221))[0] == "expired"
    assert Contract.restore(c.payload()) == c


def test_fair_queue_retains_fifo_and_prevents_hot_symbol_starvation():
    m = Mailbox(20, quantum=2)
    for i in range(10):
        assert m.put("hot", i)
    assert m.put("quiet", "risk-event")
    assert m.get(0) == [0, 1]
    assert m.get(0) == ["risk-event"]
    assert m.get(0) == [2, 3]
    m.close()
    assert not m.put("quiet", "lost")


def test_overflow_is_explicit():
    m = Mailbox(1)
    assert m.put("x", 1)
    assert not m.put("y", 2)
    assert m.status()["rejected"] == 1


def test_fair_lock_serializes_all_writers():
    lock = FairLock()
    value = [0]

    def worker():
        for _ in range(100):
            with lock:
                value[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
        assert not t.is_alive()
    assert value[0] == 1200


def test_atomic_reservation_race_same_contract(store, config):
    c = contract()
    register(store, c)
    account(store)
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(reserve(store, "demo", c, instrument(), config, 101, 100, 10000, 0.02, 0))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sum(payload is not None for payload, _ in results) == 1
    assert len(store.rows("SELECT * FROM orders")) == 1


def test_portfolio_budget_reserves_pending_orders(store, config):
    cfg = replace(config, portfolio_risk_fraction=0.001)
    account(store)
    for symbol in config.symbols:
        c = contract(symbol, symbol)
        register(store, c)
        reserve(store, "demo", c, instrument(symbol), cfg, 101, 100, 10000, 0.02, 0)
    total = store.rows("SELECT sum(reserve) AS risk FROM orders")[0]["risk"]
    assert total <= 10.0


def test_day_loss_is_hard_rejection(store, config):
    c = contract()
    register(store, c)
    account(store)
    account(store, at=102, equity=9700)
    result, reason = reserve(store, "demo", c, instrument(), config, 102, 100, 10000, 0.02, 0)
    assert result is None and reason == "risk_budget_exhausted"


def test_no_too_small_order_or_stale_account(store, config):
    c = contract()
    register(store, c)
    account(store)
    assert (
        reserve(store, "demo", c, instrument(), config, 150, 100, 10000, 0.02, 0)[1]
        == "account_stale"
    )
    assert (
        reserve(store, "demo", c, instrument(), config, 101, 100, 0.0001, 0.02, 0)[1]
        == "below_venue_minimum"
    )


def execution(ident="e1", side="Buy", qty="1", px="100", at=101000):
    return {
        "execId": ident,
        "orderLinkId": "acr-c1",
        "orderId": "v1",
        "symbol": "BTCUSDT",
        "execTime": str(at),
        "execPrice": px,
        "execQty": qty,
        "side": side,
        "execFee": ".1",
        "execType": "Trade",
    }


def test_fill_dedup_survives_restart(tmp_path):
    path = tmp_path / "db"
    s = Store(path)
    assert s.execution("demo", execution())
    assert not s.execution("demo", execution())
    s.close()
    s = Store(path)
    assert not s.execution("demo", execution())
    assert s.execution("live", execution())
    s.close()


def test_rollback_restores_reservation_transaction(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as db:
            db.execute("INSERT INTO meta VALUES('bad','1')")
            raise RuntimeError("simulated crash")
    assert store.meta("bad") is None


def book_frame(u=1, kind="snapshot"):
    return {
        "topic": "orderbook.50.BTCUSDT",
        "type": kind,
        "data": {"u": u, "b": [["99", "1000"]], "a": [["101", "1000"]]},
    }


def trade_frame(ident, px, at):
    return {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {
                "i": str(ident),
                "T": int(at * 1000),
                "s": "BTCUSDT",
                "p": str(px),
                "v": "1",
                "S": "Buy",
            }
        ],
    }


def test_real_profile_does_not_distribute_volume_across_untraded_prices():
    p = profile({100.0: 10.0, 110.0: 1.0})
    assert p == {"poc": 100.0, "val": 100.0, "vah": 100.0}


def test_book_requires_snapshot_and_trade_dedup(config):
    m = Market("BTCUSDT", config)
    m.ingest("book", book_frame(2, "delta"), 99)
    assert not m.valid
    m.ingest("book", book_frame(), 100)
    assert m.valid
    m.ingest("trades", trade_frame("a", 100, 101), 101)
    m.ingest("trades", trade_frame("a", 100, 101), 101)
    assert len(m.pending) == 1
    blocks = m.ingest("trades", trade_frame("b", 100.2, 102), 102)
    assert len(blocks) == 1 and blocks[0].volume == 2
    m.ingest("gap", {}, 103)
    assert not m.valid and not m.blocks


def test_market_labels_mature_without_any_trades_on_account(store, config):
    shared = Shared()
    shared.public_instruments["BTCUSDT"] = instrument()
    engine = Engine("BTCUSDT", store, shared, config)
    engine.process("book", book_frame(), 100)
    for i in range(12):
        engine.process("trades", trade_frame(str(i), 100 + i / 100, 101 + i), 101 + i)
    samples = store.samples(200, 100)
    assert samples
    assert all(r["available"] > r["origin"] for r in samples)
    assert not store.rows("SELECT * FROM orders")


def test_no_future_labels_in_training_and_determinism(config):
    rng = np.random.default_rng(3)
    rows = []
    for i in range(250):
        x = rng.normal(size=12)
        y = [0.01 * x[0] + rng.normal(scale=0.0001), x[1] / 5, x[4] / 10, 2.0]
        rows.append(
            {
                "id": str(i),
                "origin": i * 10.0,
                "available": i * 10.0 + 2,
                "x": x.tolist(),
                "y": y,
                "context": {"costs": 0.0001},
            }
        )
    model = train(rows, config, 1800)
    assert model is not None
    assert model.report["through"] <= 1800
    altered = [dict(r, y=[99.0, 99.0, 99.0, 99.0]) if r["available"] > 1800 else r for r in rows]
    assert train(altered, config, 1800).version == model.version
    f = model.predict(rows[0]["x"], 0.1)
    assert isinstance(f, Forecast) and f.lower <= f.upper


class FakeVenue:
    mode = "demo"

    def __init__(self):
        self.sent = []
        self.venue_orders = {}
        self.positions = []
        self.timeout_after_send = False
        self.fills = []
        self.cancels = []
        self.closes = []

    def instruments(self):
        return {"BTCUSDT": instrument(), "ETHUSDT": instrument("ETHUSDT")}

    def account(self):
        return (
            10000.0,
            self.positions,
            [
                r
                for r in self.venue_orders.values()
                if r["orderStatus"] in {"New", "PartiallyFilled"}
            ],
        )

    def executions(self, start_ms, end_ms):
        return self.fills

    def place(self, body):
        self.sent.append(body)
        self.venue_orders[body["orderLinkId"]] = {**body, "orderStatus": "New", "orderId": "v1"}
        if self.timeout_after_send:
            raise TimeoutError("accepted but response lost")
        return {"orderId": "v1"}

    def lookup(self, symbol, ident):
        return self.venue_orders.get(ident)

    def cancel(self, symbol, ident):
        self.cancels.append(ident)
        if ident in self.venue_orders:
            self.venue_orders[ident]["orderStatus"] = "Cancelled"

    def stop(self, symbol, stop):
        for pos in self.positions:
            if pos["symbol"] == symbol:
                pos["stopLoss"] = str(stop)

    def close_position(self, pos, ident):
        self.closes.append((dict(pos), ident))
        self.positions = []
        self.venue_orders[ident] = {"orderStatus": "Filled"}


def pending(store, config):
    c = contract()
    register(store, c)
    account(store)
    payload, reason = reserve(store, "demo", c, instrument(), config, 101, 100, 10000, 0.02, 0)
    assert payload, reason
    return c, payload


def test_transport_timeout_reconciles_without_duplicate_send(store, config):
    c, body = pending(store, config)
    venue = FakeVenue()
    venue.timeout_after_send = True
    executor = Executor(store, venue, config)
    executor.tick(102, True)
    assert store.rows("SELECT state FROM orders")[0]["state"] == "unknown"
    executor.reconcile(103)
    executor.tick(104, True)
    assert len(venue.sent) == 1
    assert store.rows("SELECT state FROM orders")[0]["state"] == "accepted"


def test_expired_contract_never_sends(store, config):
    pending(store, config)
    with store.transaction() as db:
        db.execute("UPDATE contracts SET state='refuted'")
    venue = FakeVenue()
    Executor(store, venue, config).tick(102, True)
    assert not venue.sent


def test_partial_fill_flatten_uses_venue_qty_not_original_order(store, config):
    pending(store, config)
    venue = FakeVenue()
    ex = Executor(store, venue, config)
    ex.tick(102, True)
    venue.positions = [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.007",
            "avgPrice": "100",
            "markPrice": "100",
            "stopLoss": "95",
        }
    ]
    venue.venue_orders["acr-c1"]["orderStatus"] = "PartiallyFilled"
    store.command("test-close", "demo", "BTCUSDT", "flatten", 103, {})
    ex.tick(103, False)
    assert venue.closes[0][0]["size"] == "0.007"
    assert "acr-c1" in venue.cancels
    ex.tick(104, False)
    assert store.rows("SELECT state FROM commands")[0]["state"] == "pending"
    ex.reconcile(105)
    ex.tick(106, False)
    assert store.rows("SELECT state FROM commands")[0]["state"] == "done"


def test_restart_sending_order_stays_unknown(store, config):
    pending(store, config)
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='sending'")
    venue = FakeVenue()
    ex = Executor(store, venue, config)
    ex.tick(102, True)
    assert not venue.sent
    assert store.rows("SELECT state FROM orders")[0]["state"] == "unknown"


def test_contract_definition_is_not_overwritten_on_transition(store, config):
    c = contract()
    register(store, c, "observing")
    engine = Engine(c.symbol, store, Shared(), config)
    engine.contract = c
    before = store.rows("SELECT definition FROM contracts")[0]["definition"]
    engine.transition("refuted", 105, "failed_reaction")
    assert store.rows("SELECT definition FROM contracts")[0]["definition"] == before
    assert json.loads(before)["model_version"] == "model"
