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


def test_recorder_publishes_public_instruments_without_a_key(tmp_path: Path) -> None:
    from capitalizator.recorder.public_rest import publish_instruments

    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    pages = {
        "": {"retCode": 0, "result": {"list": [
            {"symbol": "BTCUSDT", "status": "Trading", "priceFilter": {"tickSize": "0.1"},
             "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "minNotionalValue": "5"},
             "leverageFilter": {"maxLeverage": "100"}, "fundingInterval": 480}],
            "nextPageCursor": "p2"}},
        "p2": {"retCode": 0, "result": {"list": [
            {"symbol": "DOGEUSDT", "status": "Trading", "priceFilter": {"tickSize": "0.00001"},
             "lotSizeFilter": {"qtyStep": "1", "minOrderQty": "1", "minNotionalValue": "5"},
             "leverageFilter": {"maxLeverage": "75"}, "fundingInterval": 480}],
            "nextPageCursor": ""}},
    }

    def opener(url: str):
        cur = url.split("cursor=")[1] if "cursor=" in url else ""
        return pages[cur]

    n = publish_instruments(kn, now=datetime(2026, 9, 3, tzinfo=UTC), opener=opener)
    assert n == 2
    snap = json.loads(kn.meta("instruments_snapshot"))
    assert snap["instruments"]["DOGEUSDT"]["tick"] == "0.00001"
    kn.close()


def test_tape_replay_is_bounded_per_pass_and_resumes(tmp_path: Path) -> None:
    """VPS 2026-09-03: a restart read two days of tape into one list → 3.2 GB RSS → OOM
    loop. A pass now stops at its byte/row budget, reports `backlog`, and the next pass
    resumes exactly where it stopped; nothing is lost or duplicated. Old book deltas are
    skipped on a production first pass (a book is only valid from its next snapshot)."""
    from datetime import timedelta

    from capitalizator.desk.tape import TapeCursor
    from capitalizator.recorder.sink_parquet import BufferedParquetSink
    from capitalizator.types import MarketEvent

    t0 = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    sink = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=10_000, live_jsonl=True)
    for i in range(400):
        ts = t0 + timedelta(seconds=i)
        sink.write(MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                               recv_ts=ts, seq=i, payload={"px": str(100 + i), "qty": "1", "side": "sell"}))
    # an old book delta and a fresh one
    for hours_ago, seq in ((6, 1), (0, 2)):
        ts = t0 - timedelta(hours=hours_ago)
        sink.write(MarketEvent(stream="book_diff", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                               recv_ts=ts, seq=seq, payload={"b": [["100", "1"]], "a": []}))
    sink.flush()
    sink.close()
    # jsonl: 400 trade lines ≈ 60 KB; a 16 KB budget needs several passes
    cur = TapeCursor(replay_all_first=False, max_bytes=16 * 1024, book_hours=2)
    got: list = []
    passes = 0
    while True:
        batch = cur.fresh_rows(tmp_path, now=t0 + timedelta(minutes=10))
        passes += 1
        got.extend(batch)
        if not cur.backlog:
            break
        assert passes < 50
    assert passes >= 3
    trades = [e for e in got if e.stream == "trades"]
    assert [e.seq for e in trades] == list(range(400))  # complete, in order, no duplicates
    books = [e for e in got if e.stream == "book_diff"]
    assert [e.seq for e in books] == [2]  # the 6h-old delta was skipped
    assert cur.fresh_rows(tmp_path, now=t0 + timedelta(minutes=10)) == []

    # parquet-only partition (no live feed): rows are read in bounded slices too
    old = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=100_000)
    for i in range(300):
        ts = t0 - timedelta(hours=3) + timedelta(seconds=i)
        old.write(MarketEvent(stream="trades", exchange="bybit", symbol="ETHUSDT", exchange_ts=ts,
                              recv_ts=ts, seq=i, payload={"px": "3000", "qty": "1", "side": "buy"}))
    old.flush()
    old.close()
    cur2 = TapeCursor(replay_all_first=False, max_rows=120)
    seqs: list[int] = []
    for _ in range(10):
        seqs.extend(e.seq for e in cur2.fresh_rows(tmp_path, now=t0 + timedelta(minutes=10))
                    if e.symbol == "ETHUSDT")
        if not cur2.backlog:
            break
    assert seqs == list(range(300))


def test_live_book_is_read_while_trade_parquet_is_still_backlogged(tmp_path: Path) -> None:
    """Live jsonl is the book tail. Trade parquet backlog must not skip it.

    Bybit: orderbook snapshot/delta is not publicTrade. This class already
    tails jsonl every pass; a chrono+budget walk was not doing that.
    """
    from datetime import timedelta

    from capitalizator.desk.tape import TapeCursor
    from capitalizator.recorder.sink_parquet import BufferedParquetSink
    from capitalizator.types import MarketEvent

    now = datetime(2026, 9, 4, 21, 50, tzinfo=UTC)
    old = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=100_000)
    t_old = now - timedelta(hours=20)
    for i in range(400):
        ts = t_old + timedelta(seconds=i)
        old.write(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="ETHUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                seq=i,
                payload={"px": "3000", "qty": "1", "side": "buy"},
            )
        )
    old.flush()
    old.close()
    live = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=10_000, live_jsonl=True)
    snap_ts = now - timedelta(minutes=5)
    live.write(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=snap_ts,
            recv_ts=snap_ts,
            seq=10,
            payload={"bids": [["79753.8", "12"]], "asks": [["79753.9", "8"]]},
        )
    )
    live.write(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=now,
            recv_ts=now,
            seq=11,
            payload={"b": [["79754.0", "4"]], "a": []},
        )
    )
    live.flush()
    cur = TapeCursor(replay_all_first=False, max_rows=80, book_hours=2)
    batch = cur.fresh_rows(tmp_path, now=now)
    assert cur.backlog
    streams = {e.stream for e in batch if e.symbol == "BTCUSDT"}
    assert "snapshot" in streams
    assert "book_diff" in streams


def test_tape_walk_survives_a_writer_temp_file_vanishing(tmp_path: Path) -> None:
    """The recorder writes `hour=HH.<n>.parquet.<hex>.tmp` and renames it; the desk's
    walk saw the name and then stat() failed → the desk process died (VPS 2026-09-03)."""
    import os

    from capitalizator.ops import vault as vault_mod

    part = tmp_path / "BTCUSDT" / "trades" / "date=2026-09-03"
    part.mkdir(parents=True)
    (part / "hour=20.000001.parquet").write_bytes(b"x")
    (part / "hour=20.000002.parquet.ab12.tmp").write_bytes(b"y")
    real_is_symlink = Path.is_symlink

    def racy(self: Path) -> bool:
        out = real_is_symlink(self)
        if self.name.endswith(".tmp") and self.exists():
            os.unlink(self)  # the writer renamed it away between the check and the stat
        return out

    orig = vault_mod.Path.is_symlink
    vault_mod.Path.is_symlink = racy  # type: ignore[method-assign]
    try:
        got = [p.name for p in vault_mod.iter_regular_files(tmp_path)]
    finally:
        vault_mod.Path.is_symlink = orig  # type: ignore[method-assign]
    assert got == ["hour=20.000001.parquet"]
