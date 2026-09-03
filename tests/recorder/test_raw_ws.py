"""Raw public socket: frames pass through untouched, subscribe in chunks, resubscribe."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.live_ws import LiveRecorder
from capitalizator.recorder.raw_ws import (
    MAINNET_LINEAR,
    SUBSCRIBE_CHUNK,
    TESTNET_LINEAR,
    RawPublicWs,
)


class FakeApp:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def close(self) -> None:
        self.closed = True


def _ws(**kw) -> tuple[RawPublicWs, FakeApp]:
    ws = RawPublicWs(**kw)
    app = FakeApp()
    ws._app = app  # no socket in tests; drive the callbacks by hand
    return ws, app


def test_urls_and_topic_shapes() -> None:
    assert RawPublicWs().url == MAINNET_LINEAR
    assert RawPublicWs(testnet=True).url == TESTNET_LINEAR
    ws, _ = _ws()
    ws.trade_stream(["BTCUSDT"], lambda f: None)
    ws.orderbook_stream(200, "ETHUSDT", lambda f: None)
    ws.ticker_stream(["BTCUSDT"], lambda f: None)
    ws.liquidation_stream(["BTCUSDT"], lambda f: None)
    assert ws._topics == [
        "publicTrade.BTCUSDT", "orderbook.200.ETHUSDT", "tickers.BTCUSDT", "allLiquidation.BTCUSDT",
    ]


def test_subscribe_is_chunked_and_replayed_on_reconnect() -> None:
    ws, app = _ws()
    syms = [f"S{i}USDT" for i in range(13)]
    ws.trade_stream(syms, lambda f: None)
    ws.orderbook_stream(200, syms, lambda f: None)
    ws._on_open(app)  # connection up → everything subscribed, ≤10 args per request
    subs = [m for m in app.sent if m["op"] == "subscribe"]
    assert all(len(m["args"]) <= SUBSCRIBE_CHUNK for m in subs)
    assert sum(len(m["args"]) for m in subs) == 26
    assert ws.is_connected()
    # a late subscription on a live connection goes out at once
    ws.liquidation_stream(["BTCUSDT"], lambda f: None)
    assert app.sent[-1] == {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}
    # drop → reconnect: the full topic list is sent again
    ws._on_close(app, 1006, "gone")
    assert not ws.is_connected()
    app2 = FakeApp()
    ws._app = app2
    ws._on_open(app2)
    assert sum(len(m["args"]) for m in app2.sent if m["op"] == "subscribe") == 27


def test_frames_are_routed_by_topic_prefix_and_left_untouched() -> None:
    got: dict[str, list[dict]] = {"trades": [], "book": [], "liq": [], "ctl": []}
    ws, app = _ws(on_control=got["ctl"].append, clock=lambda: 42.0)
    ws.trade_stream(["BTCUSDT"], got["trades"].append)
    ws.orderbook_stream(200, ["BTCUSDT"], got["book"].append)
    ws.liquidation_stream(["BTCUSDT"], got["liq"].append)
    delta = {"topic": "orderbook.200.BTCUSDT", "type": "delta", "ts": 1, "data": {"s": "BTCUSDT", "b": [["1", "2"]], "a": [], "u": 5, "seq": 9}}
    ws._on_message(app, json.dumps(delta))
    ws._on_message(app, json.dumps({"topic": "publicTrade.BTCUSDT", "type": "snapshot", "data": []}))
    ws._on_message(app, json.dumps({"topic": "allLiquidation.BTCUSDT", "type": "snapshot", "data": [{"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "2"}]}))
    ws._on_message(app, json.dumps({"op": "pong", "success": True}))
    ws._on_message(app, "not json")
    assert got["book"] == [delta]  # the delta is a delta, not a rebuilt snapshot
    assert len(got["trades"]) == 1 and len(got["liq"]) == 1
    assert got["ctl"] == [{"op": "pong", "success": True}] and ws.last_pong_mono == 42.0
    assert ws.frames == 5


def test_ping_is_the_venue_op_frame_and_exit_closes() -> None:
    ws, app = _ws()
    ws._on_open(app)
    ws._send({"op": "ping"})
    assert app.sent[-1] == {"op": "ping"}
    ws.exit()
    assert app.closed and not ws.is_connected()


class FakeRaw:
    """LiveRecorder-facing surface of RawPublicWs, driven by hand."""

    def __init__(self) -> None:
        self.cbs: dict[str, object] = {}
        self.started = False

    def trade_stream(self, syms, cb): self.cbs["trades"] = cb
    def orderbook_stream(self, depth, syms, cb): self.cbs["book"] = cb
    def ticker_stream(self, syms, cb): self.cbs["ticker"] = cb
    def liquidation_stream(self, syms, cb): self.cbs["liquidation"] = cb
    def start(self): self.started = True
    def is_connected(self): return self.started
    def exit(self): self.started = False


def test_live_recorder_writes_liquidations_and_reports_socket_state(tmp_path: Path) -> None:
    ws = FakeRaw()
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    rec = LiveRecorder(symbols=["BTCUSDT"], data_root=vault.tape, ws_factory=lambda: ws, knowledge=kn,
                       fetch_snapshot=lambda s: (_ for _ in ()).throw(RuntimeError("no rest")))
    rec.start()
    assert ws.started and "liquidation" in ws.cbs
    ws.cbs["liquidation"]({"topic": "allLiquidation.BTCUSDT", "type": "snapshot", "ts": 1725024600000,
                           "data": [{"T": 1725024600000, "s": "BTCUSDT", "S": "Buy", "v": "0.5", "p": "64000"}]})
    assert rec.drain() == 1
    st = rec.status(datetime(2026, 9, 2, tzinfo=UTC))
    assert st["streams"]["liquidation"]["events"] == 1 and st["socket_connected"] is True
    rec.sink.flush()
    parts = list(vault.tape.rglob("*.parquet"))
    assert any("liquidation" in str(p) for p in parts)
    kn.close()


def test_live_jsonl_feed_is_tailed_by_offset_and_parquet_parts_are_not_reread(tmp_path: Path) -> None:
    """Э2b: the desk reads the recorder's per-event jsonl by byte offset; the parquet
    parts of the same hour are the archive and are skipped."""
    from datetime import timedelta

    from capitalizator.desk.tape import TapeCursor
    from capitalizator.recorder.sink_parquet import BufferedParquetSink
    from capitalizator.types import MarketEvent

    t0 = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    sink = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=1000, live_jsonl=True)

    def ev(i: int) -> MarketEvent:
        ts = t0 + timedelta(seconds=i)
        return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                           recv_ts=ts, seq=i, payload={"px": str(100 + i), "qty": "1", "side": "sell"})

    for i in range(3):
        sink.write(ev(i))
    cur = TapeCursor()
    got = cur.fresh_rows(tmp_path, now=t0)
    assert [e.payload["px"] for e in got] == ["100", "101", "102"]
    assert cur.files_read == 1  # one jsonl tail
    # nothing new → nothing read
    assert cur.fresh_rows(tmp_path, now=t0) == []
    # two more events: only the new bytes are parsed
    sink.write(ev(3))
    sink.write(ev(4))
    got2 = cur.fresh_rows(tmp_path, now=t0)
    assert [e.payload["px"] for e in got2] == ["103", "104"]
    # the archive part of the same hour is skipped (same rows)
    sink.flush()
    assert sink.parts_written == 1
    assert cur.fresh_rows(tmp_path, now=t0) == []
    sink.close()
    # a partition without a live feed (old recording) is still read from parquet
    old = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=1000)
    old_ts = t0 - timedelta(hours=5)
    old.write(MarketEvent(stream="trades", exchange="bybit", symbol="ETHUSDT", exchange_ts=old_ts,
                          recv_ts=old_ts, seq=1, payload={"px": "3000", "qty": "1", "side": "buy"}))
    old.flush()
    got3 = cur.fresh_rows(tmp_path, now=t0)
    assert [e.symbol for e in got3] == ["ETHUSDT"]
    # after the first pass, partitions older than RECENT_DAYS are not scanned
    stale_ts = t0 - timedelta(days=10)
    old.write(MarketEvent(stream="trades", exchange="bybit", symbol="SOLUSDT", exchange_ts=stale_ts,
                          recv_ts=stale_ts, seq=1, payload={"px": "100", "qty": "1", "side": "buy"}))
    old.flush()
    assert cur.fresh_rows(tmp_path, now=t0) == []
