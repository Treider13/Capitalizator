from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from tests.fusion.test_contract_runtime import (
    FakeVenue,
    account,
    block,
    book_frame,
    contract,
    execution,
    instrument,
    pending,
    register,
    trade_frame,
)

from capitalizator.fusion.archive import archive_events, events
from capitalizator.fusion.config import Config
from capitalizator.fusion.context import absorption, sessions
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.exchange import Bybit, credentials
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.news import ingest, sentiment
from capitalizator.fusion.performance import metrics, venue_performance
from capitalizator.fusion.replay import ReplayVenue, compare
from capitalizator.fusion.risk import reserve
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store
from capitalizator.fusion.web import PAGE, server


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
    )


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "db")
    yield store
    store.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"workers": 1.5},
        {"workers": True},
        {"queue_capacity": "20"},
        {"risk_fraction": float("nan")},
        {"risk_fraction": 1.0},
        {"api_port": 70000},
        {"confirmation_blocks": 2},
        {"symbols": ("BTCUSDT", "BTCUSDT")},
    ],
)
def test_config_rejects_unsafe_types_and_budgets(changes):
    with pytest.raises(ValueError):
        Config(**changes)


def test_checkpoint_may_not_be_selected_after_skipping_evidence():
    assert contract().evaluate(block(ident=3))[1] == "checkpoint_missing"


def test_archiver_does_not_delete_new_interleaved_receipts(store, tmp_path):
    store.event(1, "BTCUSDT", "book", {})
    store.event(99, "ETHUSDT", "book", {})
    store.event(2, "BTCUSDT", "trades", {})
    assert archive_events(store, tmp_path, 50, 2) == 0
    assert len(store.rows("SELECT * FROM events")) == 3
    assert archive_events(store, tmp_path, 100, 3) == 3
    ident = store.event(101, "BTCUSDT", "ticker", {})
    assert ident == 4
    assert [e["id"] for e in events(store, tmp_path)] == [1, 2, 3, 4]


def test_archive_corruption_is_detected(store, tmp_path):
    store.event(1, "BTCUSDT", "book", {})
    archive_events(store, tmp_path, 10, 1)
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = next((tmp_path / "archive").glob("*.parquet"))
    rows = pq.read_table(path).to_pylist()
    rows[0]["body"] = '{"tampered":true}'
    pq.write_table(pa.Table.from_pylist(rows), path)
    with pytest.raises(ValueError, match="checksum"):
        list(events(store, tmp_path))


def test_cost_label_is_fixed_at_origin_not_at_future_resolution(store, config):
    engine = Engine("BTCUSDT", store, Shared(), config)
    engine._learn(block(ident=1, at=100), 0.001)
    engine._learn(block(ident=2, at=101), 0.1)
    engine._learn(block(ident=3, at=102), 0.9)
    assert store.samples(200, 20)[0]["context"]["costs"] == 0.001


def test_revoked_send_permission_cancels_durable_pending_order(store, config):
    pending(store, config)
    venue = FakeVenue()
    Executor(store, venue, config, authorize=lambda _: False).tick(102, True)
    assert venue.sent == []
    assert store.rows("SELECT state FROM orders")[0]["state"] == "cancelled"


@pytest.mark.parametrize("code", [10000, 10016, 110072])
def test_server_error_or_duplicate_id_does_not_release_risk(store, config, code):
    from capitalizator.fusion.exchange import VenueError

    pending(store, config)
    venue = FakeVenue()

    def ambiguous(body):
        venue.sent.append(body)
        raise VenueError(code)

    venue.place = ambiguous
    Executor(store, venue, config).tick(102, True)
    order = store.rows("SELECT * FROM orders")[0]
    assert order["state"] == "unknown" and order["reserve"] > 0
    assert len(venue.sent) == 1


def test_pause_ack_linearizes_after_inflight_send_and_blocks_next(store, config):
    pending(store, config)
    venue = FakeVenue()
    lock, entered, release, acknowledged = (
        threading.Lock(),
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    allowed = [True]
    original = venue.place

    def slow(body):
        entered.set()
        assert release.wait(3)
        return original(body)

    venue.place = slow
    executor = Executor(store, venue, config, entry_lock=lock, authorize=lambda _: allowed[0])
    sender = threading.Thread(target=lambda: executor.tick(102, True))

    def pause():
        with lock:
            allowed[0] = False
            acknowledged.set()

    sender.start()
    assert entered.wait(3)
    controller = threading.Thread(target=pause)
    controller.start()
    assert not acknowledged.wait(0.02)
    release.set()
    sender.join(3)
    controller.join(3)
    assert acknowledged.is_set() and len(venue.sent) == 1
    assert not sender.is_alive() and not controller.is_alive()


def test_actual_partial_close_has_one_id_after_timeout(store, config):
    pending(store, config)
    venue = FakeVenue()
    venue.positions = [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": ".01",
            "avgPrice": "100",
            "markPrice": "100",
            "stopLoss": "95",
        }
    ]
    calls = []

    def timeout(pos, ident):
        calls.append(ident)
        raise TimeoutError("unknown close acknowledgement")

    venue.close_position = timeout
    executor = Executor(store, venue, config)
    store.command("close", "demo", "BTCUSDT", "flatten", 102, {})
    with pytest.raises(TimeoutError):
        executor.tick(102, False)
    executor.tick(103, False)
    assert len(calls) == 1


def test_pnl_dedup_funding_and_rebuild_after_late_fill(store):
    store.execution("demo", execution("entry", at=100000))
    first = venue_performance(store, "demo")
    assert first["closed_episodes"] == 0
    store.execution("demo", execution("exit", side="Sell", px="110", at=102000))
    assert venue_performance(store, "demo")["realized_net"] == pytest.approx(9.8)
    funding = {
        "execId": "funding",
        "symbol": "BTCUSDT",
        "execTime": "101000",
        "execFee": ".5",
        "execType": "Funding",
    }
    store.execution("demo", funding)
    assert not store.execution("demo", funding)
    report = venue_performance(store, "demo")
    assert report["realized_net"] == pytest.approx(9.3)
    assert report["episodes"]["net"] == pytest.approx(9.3)
    assert venue_performance(store, "demo") == report


def test_compounded_drawdown_and_return():
    report = metrics([0.1, -0.1], compound=True)
    assert report["max_drawdown"] == pytest.approx(0.1)
    assert report["net"] == pytest.approx(-0.01)


def test_local_sessions_follow_dst_and_overlap():
    winter = datetime(2026, 1, 7, 13, 30, tzinfo=UTC).timestamp()
    summer = datetime(2026, 7, 7, 12, 30, tzinfo=UTC).timestamp()
    assert set(sessions(winter)) == {"london", "new_york"}
    assert set(sessions(summer)) == {"london", "new_york"}
    assert absorption(-1, 1, 0, 0.01) > 0
    assert absorption(1, -1, 0, 0.01) < 0


def test_news_first_seen_does_not_move_on_repeated_fetch(store):
    payload = {
        "result": {
            "list": [
                {
                    "title": "Exchange hack and outage",
                    "description": "",
                    "url": "https://example.org/event",
                    "dateTimestamp": 99000,
                }
            ]
        }
    }
    first, later = ingest(store, payload, 100), ingest(store, payload, 120)
    assert first[0].known_at == later[0].known_at
    assert sentiment("no outage") > 0
    assert not ingest(store, payload, 10000)


def test_real_bybit_demo_endpoint_not_testnet(config):
    venue = Bybit("demo", ("test-key", "test-secret"), config)
    assert venue.http.endpoint == "https://api-demo.bybit.com"
    assert (
        Bybit("live", ("test-key", "test-secret"), config).http.endpoint == "https://api.bybit.com"
    )


def test_credentials_are_separate_private_files_and_not_returned(tmp_path, config):
    runtime = Runtime(tmp_path, config)
    try:
        runtime.control("pause", {"paused": True})
        runtime.control(
            "credentials", {"mode": "demo", "key": "demo-key", "secret": "secret-value"}
        )
        assert credentials(tmp_path, "demo") == ("demo-key", "secret-value")
        assert (tmp_path / "secrets/demo.json").stat().st_mode & 0o777 == 0o600
        assert "secret-value" not in json.dumps(runtime.status())
        assert runtime.control("mode", {"mode": "demo"})["status"] == "unchanged"
        assert runtime.mode_request is None
        with pytest.raises(ValueError, match="passed chronological"):
            runtime.control("mode", {"mode": "live"})
    finally:
        runtime.close()


def test_unqualified_latest_model_does_not_replace_active_on_restart(tmp_path, config):
    runtime = Runtime(tmp_path, config)
    with runtime.store.transaction() as db:
        for version, at, passed in (("champion", 1, True), ("failed", 2, False)):
            db.execute(
                "INSERT INTO models VALUES(?,?,?,?)",
                (
                    version,
                    at,
                    json.dumps({"config": config.version}),
                    json.dumps({"passed": passed}),
                ),
            )
    runtime.store.put_meta("active_model", "champion")
    runtime.close()
    reopened = Runtime(tmp_path, config)
    assert reopened.shared.atlas.version == "champion"
    reopened.close()


def test_threaded_runtime_starts_without_btc_day_and_joins(tmp_path, config, monkeypatch):
    monkeypatch.setattr("capitalizator.fusion.runtime.credentials", lambda *_: None)
    runtime = Runtime(tmp_path, config)
    runtime.start(public=False)
    try:
        runtime.callback(book_frame())
        for i in range(100):
            frame = trade_frame(i, 100 + i / 100, time.time())
            runtime.callback(frame)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not runtime.shared.snapshots:
            runtime.supervisor.stop.wait(0.01)
        assert runtime.shared.snapshots["BTCUSDT"]["valid"]
        assert runtime.shared.mode == "demo"
        assert not runtime.supervisor.failed.is_set()
        assert {t.name for t in runtime.supervisor.threads} >= {
            "market-0",
            "market-1",
            "broker",
            "trainer",
        }
    finally:
        runtime.close()
    assert all(not thread.is_alive() for thread in runtime.supervisor.threads)


def test_console_csrf_host_validation_and_readable_script(tmp_path, config):
    runtime = Runtime(tmp_path, config)
    # Bind an available port, then advertise the real port to the handler.
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    http = server(runtime, port)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}"
        with urlopen(url, timeout=3) as response:
            page = response.read().decode()
        token = page.split("const token='")[1].split("'")[0]
        assert 'src="/assets/dashboard.js"' in PAGE
        with urlopen(url + "/assets/dashboard.js", timeout=3) as response:
            assert "function connectChart()" in response.read().decode()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/api/pause", data=b'{"paused":true}', method="POST"), timeout=3)
        assert error.value.code == 403
        request = Request(
            url + "/api/pause",
            data=b'{"paused":true}',
            method="POST",
            headers={"X-Control-Token": token, "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            assert json.load(response)["paused"]
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)
        runtime.close()


def setup_venue(config, latency=0.2):
    venue = ReplayVenue({s: instrument(s) for s in config.symbols}, config, latency=latency)
    venue.advance("BTCUSDT", "book", book_frame(), 100)
    venue.place(
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "price": "99",
            "qty": "2",
            "stop": "95",
            "orderLinkId": "acr-replay",
        }
    )
    return venue


def test_replay_postonly_is_checked_on_arrival(config):
    venue = setup_venue(config)
    frame = book_frame(2)
    frame["data"]["b"], frame["data"]["a"] = [["97", "100"]], [["98", "100"]]
    venue.advance("BTCUSDT", "book", frame, 101)
    assert venue.orders["acr-replay"]["orderStatus"] == "Cancelled"
    assert not venue.fills


def test_replay_queue_partial_duplicate_and_cancel_latency(config):
    venue = setup_venue(config)
    frame = trade_frame("sell1", 99, 101)
    frame["data"][0].update(S="Sell", v="1001")
    venue.advance("BTCUSDT", "trades", frame, 101)
    assert venue.positions["BTCUSDT"]["size"] == "1.0"
    venue.advance("BTCUSDT", "trades", frame, 101.1)
    assert len(venue.fills) == 1
    venue.cancel("BTCUSDT", "acr-replay")
    venue.clock = 101.2
    venue.cancel("BTCUSDT", "acr-replay")
    assert venue.orders["acr-replay"]["cancel_at"] == pytest.approx(101.3)
    venue.advance("BTCUSDT", "ticker", {"data": {"markPrice": "99"}}, 102)
    assert venue.orders["acr-replay"]["orderStatus"] == "Cancelled"


def test_replay_funding_settles_once_with_repeated_ticker(config):
    venue = setup_venue(config)
    venue.positions["BTCUSDT"] = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "1",
        "avgPrice": "100",
        "stopLoss": "95",
    }
    data = {"data": {"markPrice": "100", "fundingRate": ".001", "nextFundingTime": "102000"}}
    for at in (101, 102, 103):
        venue.advance("BTCUSDT", "ticker", data, at)
    assert len([r for r in venue.fills if r["execType"] == "Funding"]) == 1
    assert venue.cash == pytest.approx(9999.9)


def test_ablation_replay_is_deterministic_and_uses_fresh_state(store, tmp_path, config):
    store.event(100, "BTCUSDT", "book", book_frame())
    for i in range(30):
        store.event(101 + i, "BTCUSDT", "trades", trade_frame(i, 100 + i / 100, 101 + i))
    instruments = {s: instrument(s) for s in config.symbols}
    a = compare(store, tmp_path, tmp_path / "one", config, instruments)
    b = compare(store, tmp_path, tmp_path / "two", config, instruments)
    assert a == b and a["events"] == 31
    assert set(a["definitions"]) == set("ABCD")
    assert a["D"]["venue"]["closed_episodes"] == 0
    with pytest.raises(ValueError, match="must be new"):
        compare(store, tmp_path, tmp_path / "one", config, instruments)


def test_concurrent_symbols_share_one_margin_budget(store, config):
    config = replace(
        config,
        risk_fraction=0.2,
        day_loss_fraction=0.5,
        portfolio_risk_fraction=0.5,
        margin_fraction=0.001,
    )
    account(store)
    barrier, results = threading.Barrier(2), []
    for symbol in config.symbols:
        register(store, contract(symbol, symbol))

    def run(symbol):
        barrier.wait()
        results.append(
            reserve(
                store,
                "demo",
                contract(symbol, symbol),
                instrument(symbol),
                config,
                101,
                100,
                10000,
                0.02,
                0,
            )
        )

    threads = [threading.Thread(target=run, args=(s,)) for s in config.symbols]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    payloads = [payload for payload, _ in results if payload]
    assert sum(float(p["qty"]) * float(p["price"]) / float(p["leverage"]) for p in payloads) <= 10


def test_candidate_new_reaction_risk_reservation_and_venue_send(store, config):
    from capitalizator.fusion.atlas import Forecast

    class KnownModel:
        report = {"through": 99}

        def predict(self, *_):
            # A controlled forecast tests wiring, not predictive performance.
            return Forecast(
                "controlled",
                ((0.01, 0.5, 0.2, 10),) * 3,
                ((0.01, 0.5, 0.2, 10),) * 20,
                -0.0001,
                0.02,
                0.00001,
                False,
            )

    shared = Shared()
    shared.broker_ready = True
    shared.instruments = {"BTCUSDT": instrument()}
    shared.atlas = KnownModel()
    engine = Engine("BTCUSDT", store, shared, config)
    engine.market.book(
        {
            "type": "snapshot",
            "ts": 101000,
            "data": {"u": 1, "b": [["100", "1000"]], "a": [["100.01", "1000"]]},
        },
        101,
    )
    engine.market.ticker_at = 101
    engine.market.ingest(
        "spot_book",
        {
            "generation": 1,
            "type": "snapshot",
            "ts": 101000,
            "data": {"s": "BTCUSDT", "u": 1, "b": [["100", "1000"]], "a": [["100.01", "1000"]]},
        },
        101,
    )
    for i in range(4):
        engine.market.blocks.append(block(ident=i, at=90 + i))
    c = {
        **block().context,
        "sweep_extreme": 99.9,
        "ask": 100.01,
        "bid": 100,
        "pairing": {
            "allowed": True,
            "retracement": 0.75,
            "target": 120,
            "regime": "trend",
            "anchors": {"low": 95, "high": 120},
        },
    }
    account(store, at=101)
    engine.on_block(block(ident=5, at=101, close=100, low=99.9, context=c))
    assert engine.contract_state == "observing"
    assert not store.rows("SELECT * FROM orders")
    engine.on_block(block(ident=6, at=102, close=100.1, low=100, flow=0.7, refill=0.4, context=c))
    assert len(store.rows("SELECT * FROM orders WHERE state='pending'")) == 1
    venue = FakeVenue()
    Executor(store, venue, config).tick(102, True)
    assert len(venue.sent) == 1
    assert venue.sent[0]["model_version"] == "controlled"


def test_newsgap_and_account_zero_cannot_authorize_entries(store, config):
    shared = Shared()
    shared.news_required = True
    engine = Engine("BTCUSDT", store, shared, config)
    assert not engine.news_allows(1000)
    shared.news_at = 999
    assert engine.news_allows(1000)
    assert not engine.news_allows(2000)
    register(store, contract())
    account(store, equity=0)
    assert (
        reserve(store, "demo", contract(), instrument(), config, 101, 100, 10000, 0.02, 0)[1]
        == "risk_budget_exhausted"
    )
