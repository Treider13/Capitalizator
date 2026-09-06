"""Adversarial regressions: source-to-gate propagation and exchange races."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tests.fusion.test_contract_runtime import FakeVenue, pending

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.news import calendar
from capitalizator.fusion.store import Store
from capitalizator.news_macro.ingest import NewsRow


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "ledger")
    yield value
    value.close()


def event(rule, title="Token unlock", when=110, known=100):
    return NewsRow(
        "evt",
        "OTHER",
        datetime.fromtimestamp(when, UTC),
        datetime.fromtimestamp(known, UTC),
        ("BTCUSDT",),
        "https://issuer.example",
        "UTC",
        rule,
        title,
        title,
    )


@pytest.mark.parametrize(
    "rule,title",
    [
        ("unlock_blackout", "Token unlock"),
        ("surprise_blackout", "Security breach"),
        ("surprise_blackout", "Service suspension"),
    ],
)
def test_typed_events_survive_merge_and_block_entry(store, rule, title):
    shared = Shared()
    shared.calendar = calendar((), [event(rule, title)])
    assert len(shared.calendar) == 1
    assert not Engine("BTCUSDT", store, shared, Config()).news_allows(110)


def test_linear_supply_is_visible_but_does_not_create_blackout(store):
    shared = Shared()
    shared.calendar = calendar((), [event("linear_supply_context")])
    assert len(shared.calendar) == 1
    assert Engine("BTCUSDT", store, shared, Config()).news_allows(110)


def test_late_new_notification_cannot_resurrect_cancelled_entry(store):
    cfg = Config()
    pending(store, cfg)
    executor = Executor(store, FakeVenue(), cfg)
    executor.set_state("acr-c1", "cancelled", 103)
    executor.private(
        {"topic": "order", "data": [{"orderLinkId": "acr-c1", "orderStatus": "New"}]}, 104
    )
    assert store.rows("SELECT state FROM orders")[0]["state"] == "cancelled"
    # A fill racing cancellation is material and must still be recorded.
    executor.private(
        {"topic": "order", "data": [{"orderLinkId": "acr-c1", "orderStatus": "Filled"}]}, 105
    )
    assert store.rows("SELECT state FROM orders")[0]["state"] == "filled"


def test_cancel_ack_wait_does_not_flood_exchange(store):
    cfg = Config()
    pending(store, cfg)
    venue = FakeVenue()
    executor = Executor(store, venue, cfg)
    executor.tick(102, True)
    for i in range(20):
        executor.tick(103 + i / 100, False)
    assert len(venue.cancels) == 1


def test_stuck_symbol_does_not_starve_later_exit(store):
    cfg = Config()
    venue = FakeVenue()
    executor = Executor(store, venue, cfg)
    for i in range(17):
        store.command(f"exit-{i:02}", "demo", f"COIN{i}USDT", "flatten", 100 + i, {})
    seen = []

    def handle(command, at):
        seen.append(command["symbol"])
        # Unresolved closes intentionally stay pending, as after an ambiguous send.

    executor._command = handle
    executor.tick(200, False)
    executor.tick(200.1, False)
    assert "COIN16USDT" in seen


def test_future_account_timestamp_cannot_reserve(store):
    from tests.fusion.test_contract_runtime import account, contract, instrument, register

    from capitalizator.fusion.risk import reserve

    c = contract()
    register(store, c)
    account(store, at=200)
    payload, reason = reserve(store, "demo", c, instrument(), Config(), 101, 100, 10000, 0.02, 0)
    assert payload is None and reason == "account_stale"


def test_official_ical_uses_source_time_dst_and_receipt():
    from capitalizator.fusion.macro import ical

    raw = b"""BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Consumer Price Index
DTSTART;TZID=US-Eastern:20260911T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Employment Situation
DTSTART;TZID=America/New_York:20261204T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Personal Income and Outlays
DTSTART:20260930T123000Z
END:VEVENT
END:VCALENDAR"""
    rows = ical(raw, "official", 100)
    assert [r.event_class for r in rows] == ["CPI", "NFP", "PCE"]
    assert [r.event_time.hour for r in rows] == [12, 13, 12]
    assert all(r.known_at.timestamp() == 100 for r in rows)
    cancelled = raw.replace(b"SUMMARY:Consumer", b"STATUS:CANCELLED\nSUMMARY:Consumer")
    assert len(ical(cancelled, "official", 100)) == 2
    with pytest.raises(ValueError, match="date-only"):
        ical(
            raw.replace(b"DTSTART;TZID=US-Eastern:20260911T083000", b"DTSTART;VALUE=DATE:20260911"),
            "official",
            100,
        )


def test_fed_dates_ignore_minutes_release_and_cross_month():
    from capitalizator.fusion.macro import fed

    raw = b"""<h4>2026 FOMC Meetings</h4><div><strong>January</strong></div>
<div>27-28</div><p>(Released February 18, 2026)</p>
<div>September</div><div>15-16<span>*</span></div>
<h4>2024 FOMC Meetings</h4><div>Apr/May</div><div>30-1</div>"""
    rows = fed(raw, 100)
    assert [(r.event_time.month, r.event_time.day, r.event_time.hour) for r in rows[::2]] == [
        (1, 28, 19),
        (9, 16, 18),
        (5, 1, 18),
    ]
    assert len(rows) == 6
    assert rows[1].event_time.minute == 30


def test_unlock_only_source_does_not_count_as_coin_news(tmp_path):
    from capitalizator.fusion.runtime import Runtime

    runtime = Runtime(tmp_path, Config(symbols=("ARBUSDT",)))
    try:
        runtime.news_sources = [{"name": "arb-unlock", "kind": "unlocks", "assets": ["ARBUSDT"]}]
        runtime._publish_news(
            {}, {"arb-unlock": {"ok": True, "at": 100}, "bybit": {"ok": True}}, 100
        )
        assert "coin_news_not_configured" in runtime.shared.news_coverage["ARBUSDT"]["missing"]
    finally:
        runtime.close()


def test_news_reaches_position_protection_without_trade_block(tmp_path):
    from capitalizator.fusion.runtime import Runtime

    runtime = Runtime(tmp_path, Config())
    try:
        pending(runtime.store, runtime.config)
        venue = FakeVenue()
        runtime.executor = Executor(runtime.store, venue, runtime.config)
        runtime.shared.calendar = calendar(
            (), [event("surprise_blackout", "breach", when=103, known=103)]
        )
        runtime._protect_news(103)
        commands = runtime.store.rows("SELECT * FROM commands")
        assert len(commands) == 1 and commands[0]["kind"] == "flatten"
        assert runtime.store.rows("SELECT state FROM contracts")[0]["state"] == "refuted"
        assert runtime.engines["BTCUSDT"].market.block_id == 0
    finally:
        runtime.close()


def test_conflicting_close_triggers_share_one_pending_intent(store):
    store.command("news-exit", "demo", "BTCUSDT", "flatten", 100, {})
    store.command("target-exit", "demo", "BTCUSDT", "flatten", 101, {})
    assert len(store.rows("SELECT * FROM commands WHERE state='pending'")) == 1


def test_failed_protection_does_not_skip_other_symbol(store):
    executor = Executor(store, FakeVenue(), Config())
    store.command("btc", "demo", "BTCUSDT", "flatten", 100, {})
    store.command("eth", "demo", "ETHUSDT", "flatten", 101, {})
    seen = []

    def handle(command, at):
        seen.append(command["symbol"])
        if command["symbol"] == "BTCUSDT":
            raise TimeoutError("unavailable symbol")

    executor._command = handle
    with pytest.raises(TimeoutError):
        executor.tick(200, False)
    assert seen == ["BTCUSDT", "ETHUSDT"]
    assert store.rows("SELECT error FROM dispatch WHERE id='btc'")[0]["error"] == "TimeoutError"


def test_manual_demo_profit_cannot_qualify_bot_policy(store):
    from tests.fusion.test_contract_runtime import execution

    from capitalizator.fusion.performance import venue_performance

    store.execution("demo", execution("entry", at=100000))
    store.execution("demo", execution("exit", side="Sell", px="110", at=102000))
    all_trades = venue_performance(store, "demo")
    strategy = venue_performance(store, "demo", policy=Config().version)
    assert all_trades["closed_episodes"] == 1 and all_trades["realized_net"] > 0
    assert strategy["closed_episodes"] == 0 and strategy["realized_net"] == 0
    assert strategy["ignored_executions"] == 2


def test_macro_coverage_requires_all_sources_and_expires():
    from capitalizator.fusion.macro import coverage

    rows = tuple(
        replace(event("macro_blackout", when=1000), event_class=k)
        for k in ("CPI", "NFP", "PCE", "FOMC")
    )
    health = {n: {"ok": True, "at": 100} for n in ("bls", "bea", "fed")}
    assert coverage(rows, health, 101, 180) == []
    assert "macro_source:bea" in coverage(rows, health, 400, 180)
    assert "macro_calendar_exhausted:FOMC" in coverage(rows, health, 1001, 180)


def test_session_open_inside_4h_candle_and_dst():
    from capitalizator.fusion.context import session_windows

    start = datetime(2026, 9, 6, 4, tzinfo=UTC).timestamp()
    rows = session_windows(start, start + 4 * 3600)
    london = next(r for r in rows if r["name"] == "London" and r["boundary"] == "open")
    assert datetime.fromtimestamp(london["at"], UTC).hour == 7
    winter = datetime(2026, 12, 6, 4, tzinfo=UTC).timestamp()
    rows = session_windows(winter, winter + 4 * 3600)
    assert next(r for r in rows if r["name"] == "London")["at"] == winter + 4 * 3600


def test_chart_stop_comes_from_venue_position(tmp_path):
    from capitalizator.fusion.runtime import Runtime

    runtime = Runtime(tmp_path, Config())
    try:
        pending(runtime.store, runtime.config)
        runtime.store.account(
            "demo",
            105,
            10000,
            [
                {
                    "symbol": "BTCUSDT",
                    "size": "1",
                    "stopLoss": "99",
                    "side": "Buy",
                    "avgPrice": "100",
                }
            ],
            [],
            "day",
        )
        chart = runtime.chart("BTCUSDT", "1m")
        assert chart["orders"][0]["stop"] == "95.0"
        assert chart["positions"][0]["stopLoss"] == "99"
        assert chart["account_at"] == 105
    finally:
        runtime.close()


def test_fast_news_published_while_other_source_is_still_waiting(tmp_path, monkeypatch):
    import threading
    import time

    from capitalizator.fusion.runtime import Runtime

    runtime = Runtime(tmp_path, Config())
    runtime.news_sources = [
        {"name": n, "kind": "rss", "assets": ["BTCUSDT"]} for n in ("fast", "slow")
    ]
    waiting, release, published = threading.Event(), threading.Event(), threading.Event()
    original_publish = runtime._publish_news

    def publish(cache, health, at):
        original_publish(cache, health, at)
        if any(r.event_id == "urgent" for r in runtime.shared.calendar):
            published.set()

    runtime._publish_news = publish
    monkeypatch.setattr(
        "capitalizator.fusion.runtime.fetch_news", lambda *_: {"result": {"list": []}}
    )

    def fetch(source, timeout, at, key):
        if source["name"] == "slow":
            waiting.set()
            assert release.wait(3)
            return []
        return [
            {
                "id": "urgent",
                "published": time.time(),
                "title": "Security breach",
                "url": "https://issuer.example",
                "assets": ["BTCUSDT"],
                "sentiment": -1,
            }
        ]

    monkeypatch.setattr("capitalizator.fusion.runtime.fetch_source", fetch)
    worker = threading.Thread(target=runtime._news)
    worker.start()
    try:
        assert waiting.wait(1)
        assert published.wait(1)
        assert any(r.event_id == "urgent" for r in runtime.shared.calendar)
        assert not release.is_set()
    finally:
        runtime.supervisor.stop.set()
        runtime.news_wake.set()
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        runtime.close()


def test_private_position_updates_chart_state_without_refreshing_wallet(store):
    import json

    from tests.fusion.test_contract_runtime import account

    account(store, at=100)
    executor = Executor(store, FakeVenue(), Config())
    row = {
        "symbol": "BTCUSDT",
        "positionIdx": 0,
        "side": "Buy",
        "size": "1",
        "stopLoss": "99",
        "avgPrice": "100",
        "updatedTime": "105000",
    }
    executor.private({"topic": "position", "data": [row]}, 106)
    record = store.rows("SELECT * FROM account")[0]
    assert record["at"] == 100
    assert json.loads(record["body"])["positions"][0]["stopLoss"] == "99"
    executor.private(
        {"topic": "position", "data": [{**row, "updatedTime": "104000", "stopLoss": "95"}]}, 107
    )
    assert executor.positions[0]["stopLoss"] == "99"
    executor.api.positions = [{**row, "updatedTime": "104000", "stopLoss": "95"}]
    executor.reconcile(108)
    assert executor.positions[0]["stopLoss"] == "99"


def test_news_protects_residual_position_after_entry_cancel(store):
    from tests.fusion.test_contract_runtime import account

    from capitalizator.fusion.news import protect

    pending(store, Config())
    executor = Executor(store, FakeVenue(), Config())
    executor.set_state("acr-c1", "cancelled", 102)
    account(store, at=103, positions=[{"symbol": "BTCUSDT", "size": ".01", "side": "Buy"}])
    protect(store, (event("surprise_blackout", when=103),), "demo", ("BTCUSDT",), 104, 15)
    assert store.rows("SELECT kind FROM commands")[0]["kind"] == "flatten"


def test_training_process_preserves_model_and_joins():
    import os
    import threading

    import numpy as np

    from capitalizator.fusion.atlas import train
    from capitalizator.fusion.training import TrainingProcess

    rng = np.random.default_rng(7)
    rows = [
        {
            "origin": 100 + i * 6,
            "available": 124 + i * 6,
            "x": rng.normal(size=12).tolist(),
            "y": [0.001, 0.1, 0.2, 24.0],
            "context": {"costs": 0.0012},
        }
        for i in range(128)
    ]
    expected = train(rows, Config(), 1000)
    worker = TrainingProcess()
    try:
        assert worker.process.pid != os.getpid()
        actual = worker.fit(rows, Config(), 1000, threading.Event())
        assert actual is not None and expected is not None
        assert actual.report == expected.report
        np.testing.assert_allclose(
            actual.body["coefficients"], expected.body["coefficients"], rtol=1e-10, atol=1e-12
        )
        stopped = threading.Event()
        stopped.set()
        assert worker.fit(rows, Config(), 1000, stopped) is None
    finally:
        worker.close()
    assert not worker.process.is_alive()


def test_resting_orders_do_not_starve_seventeenth_pending_entry(store):
    from tests.fusion.test_contract_runtime import account, contract, instrument, register

    from capitalizator.fusion.risk import reserve

    symbols = tuple(f"COIN{i:02}USDT" for i in range(17))
    cfg = Config(symbols=symbols, max_positions=32, risk_fraction=0.0001)
    venue = FakeVenue()
    venue.instruments = lambda: {s: instrument(s) for s in symbols}
    account(store)
    executor = Executor(store, venue, cfg)
    for i, symbol in enumerate(symbols):
        c = contract(symbol, ident=f"c{i:02}")
        register(store, c)
        payload, reason = reserve(
            store, "demo", c, instrument(symbol), cfg, 101, 100, 10000, 0.02, 0
        )
        assert payload, reason
        if i < 16:
            venue.place(payload)
            executor.set_state(payload["orderLinkId"], "accepted", 101)
    venue.sent.clear()
    executor.tick(102, True)
    assert len(venue.sent) == 1 and venue.sent[0]["symbol"] == symbols[-1]
