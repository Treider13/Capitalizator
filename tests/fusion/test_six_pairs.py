"""Six-instrument acceptance and adversarial regressions; synthetic venue data."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from urllib.request import urlopen

import pytest
from tests.fusion.test_contract_runtime import (
    FakeVenue,
    account,
    book_frame,
    contract,
    instrument,
    pending,
    register,
    trade_frame,
)

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.executor import Executor
from capitalizator.fusion.external import rss, sources, unlocks, validate_sources
from capitalizator.fusion.news import ingest, mentioned_assets
from capitalizator.fusion.risk import reserve
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store
from capitalizator.fusion.web import server

SYMBOLS = ("BTCUSDT", "ETHUSDT", "XAUUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT")


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "db")
    yield value
    value.close()


def test_default_sources_cover_each_selected_asset_and_prune_subsets(tmp_path):
    assert Config().symbols == SYMBOLS
    rows = sources(tmp_path, SYMBOLS)
    for symbol in SYMBOLS:
        assert any(r["kind"] == "rss" and symbol in r["assets"] for r in rows)
        subset = sources(tmp_path, (symbol,))
        assert all(r["assets"] == [symbol] for r in subset)
    assert [r["assets"] for r in rows if r["kind"] == "unlocks"] == [["SOLUSDT"]]


def test_news_failure_is_local_to_affected_asset(tmp_path, monkeypatch):
    monkeypatch.setattr("capitalizator.fusion.macro.coverage", lambda *args: [])
    runtime = Runtime(tmp_path, Config())
    try:
        health = {r["name"]: {"ok": True, "at": 100} for r in runtime.news_sources}
        health["bybit"] = {"ok": True, "at": 100}
        health["solana-unlocks"] = {"ok": False, "at": 100}
        runtime._publish_news({}, health, 100)
        coverage = runtime.shared.news_coverage
        assert not coverage["SOLUSDT"]["ok"]
        assert all(coverage[s]["ok"] for s in SYMBOLS if s != "SOLUSDT")
        assert not coverage["DOGEUSDT"]["unlocks_applicable"]
        assert not coverage["BNBUSDT"]["unlocks_applicable"]
        health["world-gold-council"]["at"] = -1000
        runtime._publish_news({}, health, 100)
        assert not runtime.shared.news_coverage["XAUUSDT"]["ok"]
        assert runtime.shared.news_coverage["BTCUSDT"]["ok"]
    finally:
        runtime.close()


def test_old_source_revision_cannot_restore_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr("capitalizator.fusion.macro.coverage", lambda *args: [])
    runtime = Runtime(tmp_path, Config())
    try:
        health = {r["name"]: {"ok": True, "at": 100} for r in runtime.news_sources}
        health["bybit"] = {"ok": True, "at": 100}
        runtime._publish_news({}, health, 100, 0)
        assert runtime.shared.news_coverage["BTCUSDT"]["ok"]
        runtime.control("pause", {"paused": True})
        runtime.control("news_sources", {"sources": runtime.news_sources})
        runtime._publish_news({}, health, 101, 0)
        assert not runtime.shared.news_coverage
        runtime._publish_news({}, health, 102, 1)
        assert runtime.shared.news_coverage["BTCUSDT"]["ok"]
    finally:
        runtime.close()


def test_asset_filter_uses_atom_summary_and_word_boundaries():
    source = {
        "name": "market",
        "url": "https://news.example/feed",
        "assets": list(SYMBOLS),
        "match_assets": True,
    }
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>Network notice</title><summary>Solana outage reported</summary>
    <published>1970-01-01T00:01:00Z</published><link href="https://news.example/1"/>
    </entry><entry><title>Goldman consolidated results</title>
    <published>1970-01-01T00:01:00Z</published></entry></feed>"""
    rows = rss(xml, source, 100)
    assert len(rows) == 1
    assert rows[0]["assets"] == ["SOLUSDT"] and rows[0]["sentiment"] < 0
    assert mentioned_assets("DOGEUSDT and Gold", SYMBOLS) == ["XAUUSDT", "DOGEUSDT"]


def test_filtered_source_cannot_claim_all_assets():
    with pytest.raises(ValueError, match="explicit assets"):
        validate_sources(
            [
                {
                    "name": "x",
                    "kind": "rss",
                    "url": "https://news.example",
                    "assets": ["ALL"],
                    "match_assets": True,
                }
            ],
            SYMBOLS,
        )


def test_malformed_unlock_success_does_not_mean_no_events():
    with pytest.raises(ValueError, match="event list"):
        unlocks({"status": True}, {"name": "sol", "assets": ["SOLUSDT"]}, 100)


def test_bybit_symbol_specific_surprise_does_not_flatten_every_asset(store):
    payload = {
        "result": {"list": [{"title": "SOLUSDT trading suspension", "dateTimestamp": 99000}]}
    }
    rows = ingest(store, payload, 100)
    assert rows[0].assets == ("SOLUSDT",)


@pytest.mark.parametrize("symbol", SYMBOLS)
@pytest.mark.parametrize("side", (1, -1))
def test_each_instrument_honors_margin_leverage_and_structural_stop(store, symbol, side):
    cfg = Config(trade_margin_fraction=0.001, leverage=10)
    c = replace(
        contract(), symbol=symbol, side=side, invalidation=100 - side * 5, target=100 + side * 30
    )
    register(store, c)
    account(store)
    spec, reason = reserve(store, "demo", c, instrument(symbol), cfg, 101, 100, 10000, 0.02, 0)
    assert spec, reason
    assert float(spec["qty"]) * float(spec["price"]) / float(spec["leverage"]) <= 10
    assert float(spec["leverage"]) <= 10
    assert float(spec["stop"]) == c.invalidation


@pytest.mark.parametrize("side", (1, -1))
def test_wide_stop_rejects_entry_without_clipping(store, side):
    c = replace(contract(), side=side, invalidation=100 - side * 6, target=100 + side * 30)
    spec, reason = reserve(store, "demo", c, instrument(), Config(), 101, 100, 10000, 0.02, 0)
    assert spec is None and reason == "stop_distance_limit"
    assert not store.rows("SELECT * FROM orders")


def test_concurrent_pair_budget_counts_pending_entries(store):
    cfg = Config(max_positions=2)
    account(store)
    for i, symbol in enumerate(SYMBOLS[:3]):
        c = replace(contract(), id=f"cap-{i}", symbol=symbol)
        register(store, c)
        spec, reason = reserve(store, "demo", c, instrument(symbol), cfg, 101, 100, 10000, 0.02, 0)
        if i < 2:
            assert spec, reason
        else:
            assert spec is None and reason == "position_limit"


def test_no_training_labels_before_instrument_metadata(store):
    cfg = Config(block_trades=2, context_blocks=4, horizon_blocks=2)
    engine = Engine("BTCUSDT", store, Shared(), cfg)
    engine.process("book", book_frame(), 100)
    for i in range(12):
        engine.process("trades", trade_frame(str(i), 100 + i / 100, 101 + i), 101 + i)
    assert not store.samples(200, 100)
    assert any(
        "instrument_metadata_missing" in r["body"] for r in store.rows("SELECT body FROM decisions")
    )


def test_flatten_survives_empty_snapshot_then_late_fill(store):
    cfg = Config()
    pending(store, cfg)
    venue = FakeVenue()
    ex = Executor(store, venue, cfg)
    ex.tick(102, True)
    store.command("late", "demo", "BTCUSDT", "flatten", 103, {})
    ex.tick(103, False)
    assert store.rows("SELECT state FROM commands WHERE id='late'")[0]["state"] == "pending"
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
    ex.tick(104, False)
    assert venue.closes[0][0]["size"] == "0.007"
    ex.reconcile(105)
    ex.tick(106, False)
    assert store.rows("SELECT state FROM commands WHERE id='late'")[0]["state"] == "done"


def test_settings_persist_only_while_paused_and_flat(tmp_path):
    runtime = Runtime(tmp_path, Config())
    try:
        body = {
            "max_positions": 6,
            "trade_margin_fraction": 0.15,
            "max_stop_fraction": 0.03,
            "leverage": 10,
        }
        with pytest.raises(ValueError, match="pause"):
            runtime.control("settings", body)
        runtime.control("pause", {"paused": True})
        result = runtime.control("settings", body)
        assert result["status"] == "restart_requested"
        saved = Config.load(tmp_path / "config.json")
        assert saved.symbols == SYMBOLS and saved.max_positions == 6
        assert saved.max_stop_fraction == 0.03 and saved.leverage == 10
        assert runtime.store.meta("paused")
        with pytest.raises(ValueError, match="restart"):
            runtime.control("pause", {"paused": False})
    finally:
        runtime.close()


def test_active_order_prevents_settings_restart(tmp_path):
    runtime = Runtime(tmp_path, Config())
    try:
        pending(runtime.store, runtime.config)
        runtime.control("pause", {"paused": True})
        with pytest.raises(ValueError, match="resolve orders"):
            runtime.control("settings", {"leverage": 3})
        assert not runtime.restart_requested.is_set()
        assert not (tmp_path / "config.json").exists()
        assert (
            json.loads(runtime.store.rows("SELECT body FROM orders")[0]["body"])["leverage"]
            == "2.0"
        )
    finally:
        runtime.close()


def test_actual_fill_wider_than_stop_budget_queues_exit(store):
    cfg = Config()
    pending(store, cfg)
    venue = FakeVenue()
    ex = Executor(store, venue, cfg)
    ex.positions = [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.007",
            "avgPrice": "110",
            "markPrice": "110",
            "stopLoss": "95",
        }
    ]
    ex._protect(103)
    assert (
        store.rows("SELECT kind FROM commands WHERE id='risk-exit-acr-c1'")[0]["kind"] == "flatten"
    )


def test_six_symbol_workers_publish_chart_and_terminate(tmp_path, monkeypatch):
    monkeypatch.setattr("capitalizator.fusion.runtime.credentials", lambda *_: None)
    cfg = Config(block_trades=2, block_seconds=0.001, context_blocks=4, horizon_blocks=2)
    runtime = Runtime(tmp_path, cfg)
    runtime.shared.public_instruments = {s: instrument(s) for s in SYMBOLS}
    runtime.start(public=False)
    try:
        at = time.time() - 1

        def enqueue(symbol, kind, frame, receipt):
            assert runtime.mailboxes[runtime.routes[symbol]].put(
                symbol, (symbol, kind, frame, receipt, runtime.epoch)
            )

        for symbol in SYMBOLS:
            frame = book_frame()
            frame["topic"] = "orderbook.50." + symbol
            enqueue(symbol, "book", frame, at)
        for i in range(16):
            for symbol in SYMBOLS:
                frame = trade_frame(f"{symbol}-{i}", 100 + i / 100, at + i * 0.01)
                frame["topic"] = "publicTrade." + symbol
                frame["data"][0]["s"] = symbol
                enqueue(symbol, "trades", frame, at + i * 0.01)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with runtime.shared.lock:
                ready = all(runtime.shared.snapshots.get(s, {}).get("block") for s in SYMBOLS)
            if ready:
                break
            runtime.supervisor.stop.wait(0.01)
        assert ready
        assert not runtime.supervisor.failed.is_set()
        assert not runtime.rejected_frames
        for symbol in SYMBOLS:
            chart = runtime.chart(symbol, "1m")
            assert chart["book_levels"]["bids"] and chart["block"]
    finally:
        runtime.close()
    assert all(not t.is_alive() for t in runtime.supervisor.threads)


def test_console_instance_changes_with_control_token(tmp_path):
    runtime = Runtime(tmp_path, Config())
    observed = []
    try:
        for _ in range(2):
            http = server(runtime, 0)
            thread = threading.Thread(target=http.serve_forever)
            thread.start()
            try:
                url = f"http://127.0.0.1:{http.server_port}"
                with urlopen(url, timeout=3) as response:
                    page = response.read().decode()
                with urlopen(url + "/api/status", timeout=3) as response:
                    status = json.load(response)
                instance = page.split("const consoleInstance='")[1].split("'")[0]
                token = page.split("const token='")[1].split("'")[0]
                assert instance == status["console_instance"]
                observed.append((instance, token))
            finally:
                http.shutdown()
                http.server_close()
                thread.join(3)
    finally:
        runtime.close()
    assert observed[0][0] != observed[1][0]
    assert observed[0][1] != observed[1][1]
