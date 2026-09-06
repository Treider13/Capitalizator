"""Regression tests from the September 6 review; fixtures are not trading evidence."""

from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from tests.fusion.test_contract_runtime import block, contract, register

from capitalizator.fusion.config import Config
from capitalizator.fusion.contracts import propose
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.external import gamma, rss, sources, unlocks
from capitalizator.fusion.flow import Flow
from capitalizator.fusion.market import Market
from capitalizator.fusion.public import RawPublic
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store
from capitalizator.fusion.structure import Structure, parse_history
from capitalizator.zones.model import Bar


class Socket:
    def __init__(self, url, **callbacks):
        self.callbacks = callbacks
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.sent = []

    def send(self, body):
        self.sent.append(json.loads(body))

    def run_forever(self, **kwargs):
        self.callbacks["on_open"](self)
        self.callbacks["on_message"](self, '{"op":"subscribe","success":true}')
        self.ready.set()
        self.closed.wait(5)

    def close(self):
        self.closed.set()


def test_public_wire_preserves_raw_delta_refill_and_joins():
    market = Market("BTCUSDT", Config())

    def callback(frame):
        market.book(frame, 100)

    wire = RawPublic(("BTCUSDT",), callback, factory=Socket)
    try:
        assert wire.ws.ready.wait(1)
        assert wire.is_connected()
        for kind, u, qty in (("snapshot", 10, "1"), ("delta", 11, "4")):
            frame = {
                "topic": "orderbook.50.BTCUSDT",
                "type": kind,
                "data": {"u": u, "b": [["100", qty]], "a": [["101", "1"]]},
            }
            wire._message(wire.ws, json.dumps(frame))
        assert market.refill == 3  # pybit's snapshot rewriting previously made this zero.
        assert market.bids[100] == 4
    finally:
        wire.exit()
    assert not wire.thread.is_alive() and not wire.heartbeat.is_alive()


def test_public_rejected_subscription_never_ready():
    wire = RawPublic(("BTCUSDT",), lambda _: None, factory=Socket)
    try:
        assert wire.ws.ready.wait(1)
        wire._message(wire.ws, '{"op":"subscribe","success":false}')
        assert not wire.is_connected()
        assert wire.error == "ValueError"
    finally:
        wire.exit()


def test_market_admission_does_not_wait_for_slow_network_writer(tmp_path):
    store = Store(tmp_path / "db")
    shared = Shared()
    engine = Engine("BTCUSDT", store, shared, Config())
    engine.contract = contract()
    register(store, engine.contract)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def network():
        with shared.entry_lock:
            entered.set()
            release.wait(5)

    def actor():
        engine._send(block(), None, None, "demo", False, 0)
        finished.set()

    slow = threading.Thread(target=network)
    fast = threading.Thread(target=actor)
    slow.start()
    try:
        assert entered.wait(1)
        fast.start()
        assert finished.wait(0.5), "market actor blocked behind exchange IO"
        assert not release.is_set()
    finally:
        release.set()
        slow.join(2)
        fast.join(2)
        store.close()


def test_flow_memory_independent_of_burst_size():
    flow = Flow()
    fields = set(vars(flow))
    for i in range(100000):
        flow.append((100 + i % 3, 2, 1 if i % 2 else -1))
    assert set(vars(flow)) == fields
    assert flow.n == 100000 and flow.volume == 200000 and flow.delta == 0
    assert (flow.open, flow.high, flow.low, flow.close) == (100, 102, 100, 100)
    flow.clear()
    assert not flow and flow.volume == 0


def make_bars(tf, seconds, prices, end=20000):
    rows = []
    for i, p in enumerate(prices):
        start = datetime.fromtimestamp(end - (len(prices) - i) * seconds, UTC)
        rows.append(
            Bar(
                symbol="BTCUSDT",
                tf=tf,
                open_ts=start,
                close_ts=start + timedelta(seconds=seconds),
                open=Decimal(p),
                high=Decimal(p + 1),
                low=Decimal(p - 1),
                close=Decimal(p),
                volume=Decimal(10),
            )
        )
    return rows


PRICES = [100, 103, 106, 104, 101, 102, 108, 111, 109, 104, 105, 112, 116, 113, 108, 109, 110]


@pytest.mark.parametrize("side", [1, -1])
def test_real_closed_swings_pair_directional_fib_and_local_sweep(side):
    prices = PRICES if side == 1 else [220 - p for p in PRICES]
    structure = Structure()
    for bar in make_bars("15m", 900, prices) + make_bars("1m", 60, prices):
        structure.add(bar, 0.01)
    h = structure.cache["15m"]
    assert h["trend"] == side
    assert h["swings"]["from"] < h["swings"]["to"]
    result = structure.pair(
        side,
        108 if side == 1 else 112,
        106.5 if side == 1 else 111,
        109 if side == 1 else 113.5,
        20001,
    )
    assert result["allowed"]
    assert 0.5 <= result["retracement"] <= 1
    assert result["known_at"] <= 20001
    assert not structure.pair(side, 108 if side == 1 else 112, 107.5, 112.5, 20001)["allowed"]
    assert not structure.pair(side, 108, 106, 113, 30000)["allowed"]


def test_unconfirmed_pivot_cannot_repaint_past_structure():
    structure = Structure()
    bars = make_bars("15m", 900, PRICES)
    for bar in bars[:13]:
        structure.add(bar, 0.01)
    known = structure.cache["15m"]
    assert all(p["at"] != bars[12].open_ts.timestamp() for p in known["highs"])
    structure.add(bars[13], 0.01)
    structure.add(bars[14], 0.01)
    assert structure.cache["15m"]["highs"][-1]["at"] == bars[12].open_ts.timestamp()
    assert known["highs"] != structure.cache["15m"]["highs"]


def test_backfill_excludes_forming_and_does_not_create_orderflow_labels(tmp_path):
    raw = [["0", "100", "102", "99", "101", "10"], ["60000", "101", "103", "100", "102", "11"]]
    assert len(parse_history("BTCUSDT", "1m", raw, 61)) == 1
    store = Store(tmp_path / "db")
    engine = Engine("BTCUSDT", store, Shared(), Config())
    engine.process("history", {"tf": "1m", "rows": raw}, 61)
    assert len(engine.market.structure.bars["1m"]) == 1
    assert not engine.market.blocks and not store.samples(1000, 10)
    store.close()


def test_no_htf_pair_is_a_hard_veto():
    # Veto occurs before the forecast is even consulted.
    assert propose("BTCUSDT", block(), None, Config(), 0.001, 0.01)[1] == "htf_ltf_unconfirmed"


def test_coin_news_freshness_and_missing_coverage_are_independent(tmp_path):
    store = Store(tmp_path / "db")
    shared = Shared()
    shared.news_required, shared.news_at = True, 100
    shared.news_coverage = {"BTCUSDT": {"ok": True, "at": 100}, "ETHUSDT": {"ok": False, "at": 100}}
    assert Engine("BTCUSDT", store, shared, Config()).news_allows(101)
    assert not Engine("ETHUSDT", store, shared, Config()).news_allows(101)
    assert not Engine("BTCUSDT", store, shared, Config()).news_allows(400)
    store.close()


@pytest.mark.parametrize("body", [b"<!DOCTYPE foo><rss/>", b"<html/>", b"<rss><bad>"])
def test_invalid_rss_never_reports_healthy(body):
    with pytest.raises((ValueError, ET.ParseError)):
        rss(body, {"name": "issuer", "url": "https://example.org", "assets": ["BTCUSDT"]}, 100)


def test_atom_asset_mapping_and_published_clock():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Network outage</title>
    <published>2026-09-06T10:00:00Z</published><link href="https://example.org/incident"/>
    </entry></feed>"""
    at = datetime(2026, 9, 6, 10, 1, tzinfo=UTC).timestamp()
    source = {"name": "issuer", "url": "https://example.org", "assets": ["ETHUSDT"]}
    row = rss(xml, source, at)[0]
    assert row["assets"] == ["ETHUSDT"] and row["sentiment"] < 0
    assert rss(xml, source, at - 120) == []


def test_gamma_has_no_invented_dealer_sign():
    row = {
        "symbol": "BTC-25DEC26-100000-C",
        "openInterest": "2",
        "gamma": ".001",
        "underlyingPrice": "100000",
        "markIv": ".6",
    }
    result = gamma([row], 100)
    assert result["gross_gamma_1pct"] == 200000
    assert result["dealer_sign"] == "unknown" and result["weighted_iv"] == 0.6
    assert not gamma([], 100)["available"]
    with pytest.raises(ValueError):
        gamma([{**row, "gamma": "NaN"}], 100)


@pytest.mark.parametrize("method,precision", [("AI", "second"), ("INTERNAL", "month")])
def test_unlock_low_precision_or_ai_dates_do_not_become_minute_events(method, precision):
    payload = {
        "status": True,
        "data": [
            {
                "listedMethod": method,
                "unlockDate": "2026-09-07T10:00:00Z",
                "cliffUnlocks": {
                    "cliffAmount": 100,
                    "allocationBreakdown": [{"unlockPrecision": precision}],
                },
            }
        ],
    }
    with pytest.raises(ValueError):
        unlocks(payload, {"name": "token", "assets": ["ARBUSDT"], "token_id": "arbitrum"}, 100)


def test_unlock_exact_verified_event_has_asset_and_first_receipt():
    payload = {
        "status": True,
        "data": [
            {
                "listedMethod": "INTERNAL",
                "tokenSymbol": "ARB",
                "unlockDate": "2026-09-07T10:00:00Z",
                "cliffUnlocks": {
                    "cliffAmount": 100,
                    "allocationBreakdown": [{"unlockPrecision": "second"}],
                },
            }
        ],
    }
    row = unlocks(payload, {"name": "token", "assets": ["ARBUSDT"], "token_id": "arbitrum"}, 100)[0]
    assert row.assets == ("ARBUSDT",) and row.known_at.timestamp() == 100
    assert row.size_rule == "unlock_blackout"


def test_source_configuration_rejects_duplicates(tmp_path):
    source = {"name": "same", "kind": "rss", "url": "https://example.org", "assets": ["BTCUSDT"]}
    (tmp_path / "news_sources.json").write_text(json.dumps([source, source]))
    with pytest.raises(ValueError):
        sources(tmp_path, ("BTCUSDT",))


def test_chart_only_sends_changed_history_and_actual_mode_fills(tmp_path):
    runtime = Runtime(tmp_path, Config())
    runtime.engines["BTCUSDT"].process(
        "history", {"tf": "1m", "rows": [["0", "100", "102", "99", "101", "10"]]}, 61
    )
    row = {
        "execId": "real-demo-fill",
        "symbol": "BTCUSDT",
        "execTime": "61000",
        "execQty": "1",
        "execPrice": "101",
        "execFee": ".01",
        "side": "Buy",
    }
    runtime.store.execution("demo", row)
    runtime.store.execution("live", {**row, "execId": "live-hidden"})
    first = runtime.chart("BTCUSDT", "1m")
    assert first["candles"][0]["close"] == 101
    assert [f["execId"] for f in first["fills"]] == ["real-demo-fill"]
    assert "candles" not in runtime.chart("BTCUSDT", "1m", first["revision"])
    runtime.close()


def test_book_restart_clears_contract_labels_and_partial_context(tmp_path):
    store = Store(tmp_path / "db")
    engine = Engine("BTCUSDT", store, Shared(), Config())
    snap = {"type": "snapshot", "data": {"u": 1, "b": [["100", "1"]], "a": [["101", "1"]]}}
    engine.process("book", snap, 100)
    engine.contract = contract()
    engine.contract_state = "observing"
    register(store, engine.contract, "observing")
    engine.unlabeled.append(block())
    engine.process("book", snap, 102)
    assert engine.contract_state == "expired" and not engine.unlabeled
    assert engine.market.valid
    assert store.rows("SELECT * FROM events WHERE kind='gap'")
    store.close()


def test_backup_contains_referenced_archive_and_consistent_sqlite(tmp_path):
    from capitalizator.fusion.archive import archive_events, events
    from capitalizator.fusion.backup import backup

    root, dest = tmp_path / "source", tmp_path / "snapshot"
    store = Store(root / "fusion.sqlite3")
    for i in range(5):
        store.event(i, "BTCUSDT", "fixture", {"i": i})
    archive_events(store, root, 100, 3)
    checksums = backup(root, dest)
    assert "fusion.sqlite3" in checksums
    copied = Store(dest / "fusion.sqlite3")
    assert [json.loads(r["body"])["i"] for r in events(copied, dest)] == list(range(5))
    store.event(6, "BTCUSDT", "fixture", {})
    assert len(list(events(copied, dest))) == 5
    copied.close()
    store.close()


def test_old_policy_samples_cannot_train_new_raw_feed_model(tmp_path):
    store = Store(tmp_path / "db")
    for i, policy in enumerate(("old", Config().version)):
        store.sample(str(i), "BTCUSDT", i + 1, i + 2, [0] * 12, [0] * 4, {"policy_version": policy})
    assert len(store.samples(100, 10)) == 2
    assert [r["id"] for r in store.samples(100, 10, Config().version)] == ["1"]
    store.close()


def test_changed_live_policy_cannot_be_resumed_without_demo_qualification(tmp_path):
    store = Store(tmp_path / "fusion.sqlite3")
    store.put_meta("mode", "live")
    store.put_meta("policy_epoch", {"version": "obsolete", "since": 0})
    store.close()
    runtime = Runtime(tmp_path, Config())
    assert runtime.shared.paused
    with pytest.raises(ValueError, match="Demo qualification"):
        runtime.control("pause", {"paused": False})
    runtime.close()


@pytest.mark.parametrize(
    "row",
    [
        ["0", "100", "99", "90", "95", "1"],
        ["0", "NaN", "100", "90", "95", "1"],
        ["1000", "100", "101", "90", "95", "1"],
        ["0", "100"],
    ],
)
def test_bad_historical_prices_or_alignment_fail_closed(row):
    with pytest.raises(ValueError):
        parse_history("BTCUSDT", "1m", [row], 200)


def test_news_closes_existing_position_even_while_model_is_absent(tmp_path):
    from tests.fusion.test_contract_runtime import account, pending

    from capitalizator.news_macro.ingest import NewsRow

    store = Store(tmp_path / "db")
    cfg, shared = Config(), Shared()
    pending(store, cfg)
    account(store, at=101, positions=[{"symbol": "BTCUSDT", "size": "1", "side": "Buy"}])
    now = datetime.fromtimestamp(101, UTC)
    shared.calendar = (
        NewsRow(
            "incident",
            "OTHER",
            now,
            now,
            ("BTCUSDT",),
            "issuer",
            "UTC",
            "surprise_blackout",
            "outage",
            "outage",
        ),
    )
    Engine("BTCUSDT", store, shared, cfg).on_block(block(at=101))
    command = store.rows("SELECT * FROM commands")[0]
    assert command["kind"] == "flatten" and json.loads(command["body"])["reason"] == "news_surprise"
    store.close()


def test_stream_sends_new_candles_and_stops_before_database_close(tmp_path):
    from urllib.request import urlopen

    from capitalizator.fusion.web import server

    runtime = Runtime(tmp_path, Config())
    http = server(runtime, 0)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    try:
        url = f"http://127.0.0.1:{http.server_address[1]}/api/stream?symbol=BTCUSDT&tf=1m"
        with urlopen(url, timeout=3) as response:
            first = json.loads(response.readline().removeprefix(b"data: "))
            assert first["candles"] == [] and first["mode"] == "demo"
            runtime.engines["BTCUSDT"].process(
                "history", {"tf": "1m", "rows": [["0", "100", "102", "99", "101", "10"]]}, 61
            )
            response.readline()
            second = json.loads(response.readline().removeprefix(b"data: "))
            assert second["candles"][0]["close"] == 101
    finally:
        runtime.supervisor.stop.set()
        http.shutdown()
        http.server_close()
        thread.join(2)
        runtime.close()
    assert not thread.is_alive()


def test_rr_is_checked_net_of_costs(tmp_path):
    from dataclasses import replace

    from tests.fusion.test_contract_runtime import account, instrument

    from capitalizator.fusion.risk import reserve

    store = Store(tmp_path / "db")
    c = replace(contract(), target=110)
    account(store)
    register(store, c)
    payload, reason = reserve(store, "demo", c, instrument(), Config(), 101, 100, 10000, 0.02, 0)
    assert payload is None and reason == "net_reward_after_costs"
    store.close()


def test_news_credentials_are_separate_private_and_not_in_status(tmp_path):
    from capitalizator.fusion.exchange import news_key

    runtime = Runtime(tmp_path, Config())
    runtime.control("news_credentials", {"key": "provider-test-secret"})
    assert news_key(tmp_path) == "provider-test-secret"
    assert (tmp_path / "secrets" / "tokenomist.json").stat().st_mode & 0o777 == 0o600
    assert "provider-test-secret" not in json.dumps(runtime.status())
    runtime.close()


def test_confirmation_cannot_chase_entry_outside_frozen_retracement(tmp_path):
    from dataclasses import replace

    store = Store(tmp_path / "db")
    engine = Engine("BTCUSDT", store, Shared(), Config())
    engine.contract = replace(
        contract(), definition={"pairing": {"anchors": {"low": 95, "high": 120}}}
    )
    assert engine.entry_location(block(context={**block().context, "bid": 100}))
    assert not engine.entry_location(block(context={**block().context, "bid": 115}))
    assert not engine.entry_location(block(context={**block().context, "bid": 94}))
    store.close()
