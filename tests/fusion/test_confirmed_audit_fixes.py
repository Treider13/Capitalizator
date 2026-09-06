"""Regressions for confirmed execution, state, journal and shutdown defects.

Assertions describe required safe behavior. All must pass with the root-cause fixes.
No real exchange, credentials, or trading calls are used.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from capitalizator.fusion.archive import archive_events, events
from capitalizator.fusion.config import Config
from capitalizator.fusion.contracts import Contract
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.exchange import Bybit, VenueError
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.performance import venue_performance
from capitalizator.fusion.replay import compare
from capitalizator.fusion.risk import Instrument, reserve
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store, encode
from capitalizator.fusion.web import server

CFG = Config(symbols=("BTCUSDT", "ETHUSDT"))
INST = Instrument("BTCUSDT", 0.01, 0.001, 0.001, 1, 10000, 10, 0.0002, 0.00055, 480)


def position(**kwargs):
    return dict(
        symbol="BTCUSDT",
        side="Buy",
        size="1",
        avgPrice="100",
        markPrice="100",
        stopLoss="95",
        positionIdx=0,
        **kwargs,
    )


def contract(ident="first"):
    return Contract(
        ident,
        "BTCUSDT",
        1,
        100,
        1,
        2,
        5,
        220,
        "model",
        CFG.version,
        100,
        95,
        120,
        0.1,
        -0.1,
        0.01,
        (0.0,) * 12,
        {},
    )


def register(store, ident="first"):
    c = contract(ident)
    with store.transaction() as db:
        db.execute(
            "INSERT INTO contracts VALUES(?,?,?,?,?,?)",
            (c.id, c.symbol, c.created, "confirmed", encode(c.payload()), c.created),
        )
    return c


def seed_order(store):
    store.account("demo", 101, 10000, [], [], "1970-01-01")
    c = register(store)
    payload, reason = reserve(store, "demo", c, INST, CFG, 101, 100, 10000, 0.02, 0)
    assert payload is not None, reason
    return payload


class Venue:
    mode = "demo"

    def __init__(self):
        self.positions = []
        self.orders = {}
        self.sent = []
        self.closes = []

    def instruments(self):
        return {"BTCUSDT": INST, "ETHUSDT": replace(INST, symbol="ETHUSDT")}

    def account(self):
        return 10000.0, list(self.positions), []

    def executions(self, *args):
        return []

    def lookup(self, symbol, ident):
        return self.orders.get(ident)

    def place(self, body):
        self.sent.append(body)
        return {"orderId": "venue"}

    def cancel(self, *args):
        return None

    def stop(self, *args):
        return None

    def close_position(self, pos, ident):
        self.closes.append(ident)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "fusion.sqlite3")
    yield s
    s.close()


def test_cancel_with_partial_fill_must_keep_reserve_until_position_reconciled(store):
    payload = seed_order(store)
    executor = Executor(store, Venue(), CFG)
    executor.set_state(payload["orderLinkId"], "partial", 102)
    # Actual fill exists; the independent position topic has not arrived yet.
    executor.private(
        {
            "topic": "order",
            "data": [
                {
                    "orderLinkId": payload["orderLinkId"],
                    "orderStatus": "Cancelled",
                    "cumExecQty": "1",
                    "updatedTime": "103000",
                }
            ],
        },
        103,
    )
    second = register(store, "second")
    admitted, reason = reserve(store, "demo", second, INST, CFG, 103, 100, 10000, 0.02, 0)
    assert admitted is None, f"Second entry admitted before position reconciliation: {reason}"


def test_rest_flat_snapshot_must_fence_delayed_old_position_notification(store):
    venue = Venue()
    executor = Executor(store, venue, CFG)
    executor.private({"topic": "position", "data": [position(updatedTime="100000")]}, 101)
    # Bybit settleCoin query can omit a symbol with zero size.
    executor.reconcile(110)
    assert executor.positions == []
    executor.private({"topic": "position", "data": [position(updatedTime="105000")]}, 111)
    assert executor.positions == [], "A pre-reconciliation position resurrected after REST flat"


def test_definitive_close_rejection_must_not_become_permanent_unknown(store):
    venue = Venue()
    venue.positions = [position()]
    attempts = []

    def reject_once(pos, ident):
        attempts.append(ident)
        if len(attempts) == 1:
            raise VenueError(10006, "Too many visits")

    venue.close_position = reject_once
    executor = Executor(store, venue, CFG)
    store.command("operator-close", "demo", "BTCUSDT", "flatten", 102, {})
    with pytest.raises(VenueError):
        executor.tick(102, False)
    for at in (108, 114, 120):
        executor.tick(at, False)
    assert len(attempts) >= 2, "Definitively rejected close is never retried"


def test_ambiguous_close_timeout_must_not_blindly_resend_control(store):
    venue = Venue()
    venue.positions = [position()]
    attempts = []

    def timeout(pos, ident):
        attempts.append(ident)
        raise TimeoutError("Outcome unknown")

    venue.close_position = timeout
    executor = Executor(store, venue, CFG)
    store.command("operator-close", "demo", "BTCUSDT", "flatten", 102, {})
    with pytest.raises(TimeoutError):
        executor.tick(102, False)
    executor.tick(108, False)
    assert len(attempts) == 1


def test_execution_history_failure_must_not_starve_operator_close(store):
    venue = Venue()
    venue.positions = [position()]

    def history_down(*args):
        raise RuntimeError("execution history unavailable, account/order API healthy")

    venue.executions = history_down
    executor = Executor(store, venue, CFG)
    store.command("operator-close", "demo", "BTCUSDT", "flatten", 102, {})
    for at in (102, 108, 114):
        try:
            executor.tick(at, False)
        except RuntimeError:
            pass
    assert venue.closes, "Read-only execution-history outage prevents every close attempt"


def test_actual_order_send_must_recheck_after_leverage_network_roundtrip(store):
    seed_order(store)
    venue = Venue()
    allowed = [True]
    wire_calls = []
    bybit = object.__new__(Bybit)

    def call(method, **params):
        wire_calls.append(method)
        if method == "set_leverage":
            # Another market/news thread revokes admission during this REST call.
            allowed[0] = False
        return {"orderId": "venue"}

    bybit.call = call
    venue.place = bybit.place
    if hasattr(bybit, "prepare_entry"):
        venue.prepare_entry = bybit.prepare_entry
    executor = Executor(store, venue, CFG, authorize=lambda _: allowed[0])
    executor.tick(102, True)
    assert "place_order" not in wire_calls, "Entry sent after authorization changed during leverage"


def test_archive_snapshot_survives_rotation_while_generator_is_suspended(store, tmp_path):
    for i in range(6):
        store.event(i + 1, "BTCUSDT", "ticker", {})
    assert archive_events(store, tmp_path, 100, 3) == 3
    writer = Store(store.path)
    reader = events(store, tmp_path)
    try:
        first = next(reader)
        assert first["id"] == 1
        assert archive_events(writer, tmp_path, 100, 3) == 3
        assert [first["id"]] + [r["id"] for r in reader] == [1, 2, 3, 4, 5, 6]
        assert len(list(events(writer, tmp_path))) == 6
    finally:
        reader.close()
        writer.close()


def test_history_provenance_fences_partial_response_after_candle_boundary(store):
    engine = Engine("BTCUSDT", store, Shared(), CFG)
    complete = [["60000", "100", "110", "90", "105", "1000"]]
    partial = [["60000", "100", "102", "99", "101", "50"]]
    engine.process("history", {"tf": "1m", "rows": complete, "known_at": 120.05}, 120.05)
    engine.process("history", {"tf": "1m", "rows": partial, "known_at": 119.9}, 120.1)
    assert engine.market.structure.cache["1m"]["candles"][-1]["high"] == 110


def test_credential_change_must_require_fresh_flat_account(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, CFG)
    try:
        runtime.shared.paused = True
        runtime.store.account("demo", 100, 10000, [], [], "1970-01-01")
        monkeypatch.setattr("capitalizator.fusion.runtime.time.time", lambda: 10000)
        with pytest.raises(ValueError, match="fresh|reconcil|stale"):
            runtime.control("credentials", {"mode": "demo", "key": "fake", "secret": "fake"})
    finally:
        runtime.close()


def test_unmanaged_acr_prefixed_order_must_consume_budget_or_block_entry(store):
    store.account(
        "demo",
        101,
        10000,
        [],
        [
            {
                "symbol": "BTCUSDT",
                "orderLinkId": "acr-foreign",
                "side": "Buy",
                "qty": "100",
                "price": "100",
                "reduceOnly": False,
            }
        ],
        "1970-01-01",
    )
    admitted, reason = reserve(store, "demo", register(store), INST, CFG, 101, 100, 10000, 0.02, 0)
    assert admitted is None, f"Unknown acr-prefix venue order bypassed risk accounting: {reason}"


def test_idle_http_client_must_not_block_server_shutdown():
    runtime = SimpleNamespace()
    http = server(runtime, 0)
    accepted = threading.Event()
    original = http.process_request

    def process(request, address):
        original(request, address)
        accepted.set()

    http.process_request = process
    listener = threading.Thread(target=http.serve_forever)
    listener.start()
    client = socket.create_connection(http.server_address, timeout=2)
    finished = threading.Event()
    closer = None
    try:
        assert accepted.wait(2)
        http.shutdown()
        listener.join(2)
        closer = threading.Thread(target=lambda: (http.server_close(), finished.set()))
        closer.start()
        assert finished.wait(0.5), "Idle accepted connection blocks server_close indefinitely"
    finally:
        client.close()
        if closer:
            closer.join(3)
        else:
            http.server_close()


def test_replay_must_survive_invalid_frame_followed_by_recorded_recovery(store, tmp_path):
    engine = Engine("BTCUSDT", store, Shared(), CFG)
    malformed = {
        "type": "snapshot",
        "ts": 101000,
        "data": {"u": 1, "b": [["100", "-1"]], "a": [["101", "2"]]},
    }
    # Same sequence as Runtime._market_worker: Engine logs the frame, then recovery logs a gap.
    with pytest.raises(ValueError, match="invalid book level"):
        engine.process("book", malformed, 101)
    engine.process("gap", {"reason": "ValueError"}, 101)
    assert len(store.rows("SELECT * FROM events")) == 2
    compare(
        store,
        tmp_path,
        tmp_path / "replay",
        CFG,
        {"BTCUSDT": INST, "ETHUSDT": replace(INST, symbol="ETHUSDT")},
    )


def test_old_inflight_book_must_not_clear_new_generation_recovery_halt(tmp_path):
    cfg = replace(CFG, symbols=("BTCUSDT",), workers=1)
    runtime = Runtime(tmp_path, cfg)
    entered, release, processed = threading.Event(), threading.Event(), threading.Event()
    original = runtime.engines["BTCUSDT"].process
    original_beat = runtime.supervisor.beat

    def process(kind, frame, at):
        original(kind, frame, at)
        if kind == "book":
            entered.set()
            assert release.wait(3)

    def beat(name):
        original_beat(name)
        processed.set()

    runtime.engines["BTCUSDT"].process = process
    runtime.supervisor.beat = beat
    now = time.time()
    runtime.callback(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": now * 1000,
            "data": {"u": 1, "b": [["100", "2"]], "a": [["100.01", "2"]]},
        },
        0,
    )
    thread = threading.Thread(target=lambda: runtime._market_worker(0))
    thread.start()
    try:
        assert entered.wait(3)
        # Mirror the generation change made concurrently by Runtime._maintenance.
        with runtime.shared.lock:
            runtime.epoch += 1
            runtime.recovering = {"BTCUSDT"}
            runtime.shared.halt("recovering_feed")
        processed.clear()
        release.set()
        assert processed.wait(3)
        assert "recovering_feed" in runtime.shared.halts, (
            "Old epoch frame acknowledged new recovery"
        )
    finally:
        release.set()
        runtime.supervisor.stop.set()
        thread.join(3)
        runtime.close()


def test_spot_execution_must_not_close_linear_inventory_in_performance(store):
    payload = seed_order(store)
    executor = Executor(store, Venue(), CFG)
    linear = {
        "category": "linear",
        "execId": "linear-fill",
        "orderLinkId": payload["orderLinkId"],
        "symbol": "BTCUSDT",
        "execTime": "102000",
        "execQty": "1",
        "execPrice": "100",
        "execFee": "0",
        "side": "Buy",
        "execType": "Trade",
        "closedSize": "0",
    }
    spot = {
        **linear,
        "category": "spot",
        "execId": "manual-spot",
        "orderLinkId": "manual-spot",
        "execTime": "103000",
        "execPrice": "120",
        "side": "Sell",
    }
    executor.private({"topic": "execution", "data": [linear, spot]}, 103)
    report = venue_performance(store, "demo", policy=CFG.version)
    assert report["closed_episodes"] == 0, f"Spot sale invented a closed futures episode: {report}"
