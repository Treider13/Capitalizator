"""Reproductions for clock and malformed-frame failures in the dual-book loop."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from tests.fusion.test_contract_runtime import trade_frame
from tests.fusion.test_cross_market import frame

from capitalizator.fusion.config import Config
from capitalizator.fusion.cross_market import SpotBook, entry_check
from capitalizator.fusion.market import Market
from capitalizator.fusion.runtime import Runtime


@pytest.mark.parametrize("exchange_at", [90, 120, None])
def test_delayed_future_or_missing_exchange_timestamp_cannot_authorize(exchange_at):
    m = Market("BTCUSDT", Config())
    future = frame(at=exchange_at or 110)
    if exchange_at is None:
        del future["ts"]
    m.ingest("book", future, 110)
    m.ingest("spot_book", frame(at=110), 110)
    assert entry_check(m.cross_market(), 1, 110, m.config) != "ready"


def test_regressed_futures_timestamp_invalidates_book():
    m = Market("BTCUSDT", Config())
    m.ingest("book", frame(at=110), 110)
    with pytest.raises(ValueError):
        m.ingest("book", frame(at=109, u=11, kind="delta"), 111)
    assert not m.valid


@pytest.mark.parametrize("exchange_at", [90, 999999])
def test_invalid_trade_time_cannot_poison_subsequent_trade_order(exchange_at):
    m = Market("BTCUSDT", Config())
    m.ingest("book", frame(at=110), 110)
    with pytest.raises(ValueError):
        m.ingest("trades", trade_frame("bad-clock", 100, exchange_at), 110)
    assert m.last_exchange_trade == 0
    m.ingest("trades", trade_frame("good-clock", 100, 111), 111)
    assert m.last_exchange_trade == 111 and m.cvd == 1


def test_malformed_spot_quantity_clears_last_valid_book():
    book = SpotBook("BTCUSDT")
    book.ingest("spot_book", frame(), 101)
    bad = frame(u=11, kind="delta")
    bad["data"]["b"][0][1] = None
    with pytest.raises((TypeError, ValueError)):
        book.ingest("spot_book", bad, 102)
    assert not book.snapshot()["valid"]


def test_malformed_spot_does_not_kill_symbol_worker(tmp_path):
    r = Runtime(tmp_path, Config())
    processed = threading.Event()
    original = r.engines["BTCUSDT"].process

    def process(kind, data, at):
        original(kind, data, at)
        if kind == "spot_status" and data["status"] == "invalid_frame":
            processed.set()

    r.engines["BTCUSDT"].process = process
    bad = frame()
    bad["data"]["b"][0][1] = None
    try:
        r.supervisor.start("market-0", lambda: r._market_worker(0))
        r._spot_event("BTCUSDT", "spot_book", bad, 0, 0)
        assert processed.wait(1), r.supervisor.errors
        assert not r.supervisor.failed.is_set()
    finally:
        r.close()


def test_queue_age_uses_elapsed_time_when_wall_clock_moves_back(tmp_path, monkeypatch):
    import capitalizator.fusion.runtime as module

    r = Runtime(tmp_path, Config())
    mono = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: 110.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: mono[0])
    r.callback(frame(at=110))
    mono[0] += 10
    original = r.engines["BTCUSDT"].process

    def process(kind, data, at):
        original(kind, data, at)
        if kind == "book":
            r.supervisor.stop.set()

    r.engines["BTCUSDT"].process = process
    try:
        r._market_worker(0)
        assert "market_processing_lag" in r.shared.halts
    finally:
        r.store.close()


def test_console_freshness_does_not_use_phone_wall_clock():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the console clock test")
    html = Path("src/capitalizator/fusion/dashboard.html").read_text()
    code = html.split("<script>", 1)[1].split("</script>", 1)[0]
    script = """
const vm=require('vm'),assert=require('assert');
let elapsed=1000;
const ctx={document:{getElementById:()=>({})},window:{addEventListener(){}},
  fetch:()=>new Promise(()=>{}),setTimeout(){},performance:{now:()=>elapsed},
  Date:class extends Date{static now(){return 9999999999999}}};
vm.createContext(ctx);vm.runInContext(CODE,ctx);
ctx.d={at:110,_received_mono:1000,max_data_age_s:5};
ctx.b={valid:true,book_at:109,exchange_at:109,category:'spot',status:'streaming'};
assert.equal(vm.runInContext('bookFresh(b,d)',ctx),true);
elapsed=7000;
assert.equal(vm.runInContext('bookFresh(b,d)',ctx),false);
""".replace("CODE", json.dumps(code))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
