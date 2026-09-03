"""D-44: a real streaming recorder. Fake pybit WebSocket replays the repo's Bybit fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capitalizator.desk.tape import TapeCursor
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.live_ws import BOOK_DEPTH, LiveRecorder
from capitalizator.recorder.rest_snapshot import BookSnapshot

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "ws"


class FakeWs:
    """Records subscriptions; `emit()` calls the callbacks like pybit's thread would."""

    def __init__(self) -> None:
        self.subs: dict[str, tuple] = {}
        self.exited = False

    def trade_stream(self, symbol, callback):
        self.subs["trades"] = (symbol, callback)

    def orderbook_stream(self, depth, symbol, callback):
        self.subs["book"] = (depth, symbol, callback)

    def ticker_stream(self, symbol, callback):
        self.subs["ticker"] = (symbol, callback)

    def exit(self) -> None:
        self.exited = True

    def emit(self, stream: str, frame: dict) -> None:
        self.subs[stream][-1](frame)


def _trade_frames() -> list[dict]:
    lines = (FIX / "btc_trades_100.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    return [{"topic": "publicTrade.BTCUSDT", "type": "snapshot", "ts": r["T"], "data": [r]} for r in rows]


def _book_frames() -> list[dict]:
    lines = (FIX / "btc_book_snapshot_20_diffs.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_live_recorder_streams_fixture_frames_into_parts(tmp_path: Path) -> None:
    ws = FakeWs()
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    rec = LiveRecorder(symbols=["BTCUSDT", "ETHUSDT"], data_root=vault.tape, ws_factory=lambda: ws,
                       knowledge=kn, fetch_snapshot=lambda s: (_ for _ in ()).throw(RuntimeError("no rest")))
    rec.start()
    assert ws.subs["book"][0] == BOOK_DEPTH and ws.subs["trades"][0] == ["BTCUSDT", "ETHUSDT"]
    for f in _trade_frames():
        ws.emit("trades", f)
    for f in _book_frames():
        ws.emit("book", f)
    ws.emit("ticker", {"topic": "tickers.BTCUSDT", "type": "snapshot", "ts": 1725024600000,
                       "data": {"symbol": "BTCUSDT", "fundingRate": "0.0001", "openInterest": "1000",
                                "markPrice": "65000.5"}})
    ws.emit("trades", {"op": "subscribe", "success": True, "ret_msg": "", "conn_id": "x"})  # control frame
    assert rec.q.qsize() == 100 + 21 + 1 + 1
    n = rec.drain()
    assert n == 123
    st = rec.status(datetime(2026, 9, 2, tzinfo=UTC))
    assert st["streams"]["trades"]["events"] == 100
    assert st["streams"]["book"]["events"] >= 21  # snapshot + diffs (+ bbo rows)
    assert st["streams"]["ticker"]["events"] == 3  # funding + oi + mark
    assert st["streams"]["trades"]["frames"] == 101 and st["dropped"] == 0
    rec.sink.flush()
    assert rec.sink.parts_written >= 3  # trades, book, funding/oi/mark partitions
    # the desk's cursor reads exactly what was streamed
    events = TapeCursor().fresh_rows(vault.tape)
    streams = {e.stream for e in events}
    assert {"trades", "snapshot", "book_diff", "funding", "oi", "mark"} <= streams
    trades = [e for e in events if e.stream == "trades"]
    assert len(trades) == 100
    # recv_ts is per frame, not one stamp per run (Н-2)
    assert len({e.recv_ts for e in trades}) > 1
    assert rec.publish_status(every_s=0)
    status = json.loads(kn.meta("recorder_status"))
    assert status["streams"]["trades"]["frames"] == 101
    kn.close()


def test_gap_in_book_is_counted_and_resynced_via_rest(tmp_path: Path) -> None:
    ws = FakeWs()
    snaps: list[str] = []

    def fetch(symbol: str) -> BookSnapshot:
        snaps.append(symbol)
        return BookSnapshot(symbol=symbol, exchange_ts=datetime(2024, 8, 30, 14, 0, tzinfo=UTC), seq=500,
                            bids=(("60000.0", "1"),), asks=(("60000.1", "1"),))

    rec = LiveRecorder(symbols=["BTCUSDT"], data_root=tmp_path / "tape", ws_factory=lambda: ws,
                       fetch_snapshot=fetch)
    (tmp_path / "tape").mkdir()
    rec.start()
    frames = _book_frames()
    ws.emit("book", frames[0])  # snapshot u=100
    ws.emit("book", frames[1])  # u=101
    gap = dict(frames[2])
    gap["data"] = {**frames[2]["data"], "u": 150}  # jump → gap
    ws.emit("book", gap)
    rec.drain()
    assert rec.stats["book"].gaps == 1
    assert snaps == ["BTCUSDT"]  # REST snapshot pulled once for the resync
    rec.sink.flush()
    events = TapeCursor().fresh_rows(tmp_path / "tape")
    resync = next(e for e in events if e.stream == "resync")
    assert resync.seq == 500 and resync.payload["bids"] == [["60000.0", "1"]]


def test_subscriptions_are_chunked_by_ten_symbols(tmp_path: Path) -> None:
    """pybit sends one request per call and does not batch; Bybit rejects `args size >10`."""

    class CountingWs(FakeWs):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, list]] = []

        def trade_stream(self, symbol, callback):
            self.calls.append(("trades", list(symbol)))
            self.subs["trades"] = (symbol, callback)

        def orderbook_stream(self, depth, symbol, callback):
            self.calls.append(("book", list(symbol)))
            self.subs["book"] = (depth, symbol, callback)

        def ticker_stream(self, symbol, callback):
            self.calls.append(("ticker", list(symbol)))
            self.subs["ticker"] = (symbol, callback)

    ws = CountingWs()
    symbols = [f"S{i}USDT" for i in range(24)]
    rec = LiveRecorder(symbols=symbols, data_root=tmp_path, ws_factory=lambda: ws)
    rec.start()
    per_stream = [c for c in ws.calls if c[0] == "trades"]
    assert len(per_stream) == 3 and [len(c[1]) for c in per_stream] == [10, 10, 4]
    assert all(len(c[1]) <= 10 for c in ws.calls)
    assert sorted(s for c in per_stream for s in c[1]) == sorted(symbols)


def test_run_loop_stops_flushes_and_exits_socket(tmp_path: Path) -> None:
    ws = FakeWs()
    rec = LiveRecorder(symbols=["BTCUSDT"], data_root=tmp_path / "tape", ws_factory=lambda: ws)
    (tmp_path / "tape").mkdir()
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            for f in _trade_frames()[:5]:
                ws.emit("trades", f)
        return calls["n"] > 2

    rec.run(should_stop=stop, sleep=lambda s: None)
    assert ws.exited
    assert rec.sink.pending() == 0 and rec.sink.flushed_count == 5
    assert rec.status()["streams"]["trades"]["events"] == 5


def test_rest_ticker_fallback_uses_injected_opener(tmp_path: Path) -> None:
    payload = {
        "retCode": 0,
        "result": {
            "category": "linear",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "fundingRate": "0.0001",
                    "openInterest": "12",
                    "markPrice": "65000.1",
                    "ts": 1725024600000,
                }
            ],
        },
    }
    hits: list[str] = []

    def opener(url: str) -> dict:
        hits.append(url)
        return payload

    (tmp_path / "tape").mkdir()
    rec = LiveRecorder(
        symbols=["BTCUSDT"],
        data_root=tmp_path / "tape",
        ws_factory=FakeWs,
        rest_fallback=True,
        rest_opener=opener,
        fetch_snapshot=lambda s: (_ for _ in ()).throw(RuntimeError("no rest")),
    )
    now = datetime(2026, 9, 2, tzinfo=UTC)
    n = rec.poll_rest_tickers(now=now)
    assert n == 3
    assert hits and "tickers" in hits[0] and "BTCUSDT" in hits[0]
    rec.stats["ticker"].last_at = now
    assert rec.poll_rest_tickers(now=now) == 0


def test_restart_and_reconnect_write_marked_time_gaps(tmp_path: Path) -> None:
    """F0 law: a recorder restart or a socket reconnect is a MARKED hole (gap event
    with ts_from/ts_to). Unmarked holes are what the 24h gate refuses."""
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    ws = FakeWs()
    ws.reconnects = 0
    rec = LiveRecorder(symbols=["BTCUSDT"], data_root=vault.tape, ws_factory=lambda: ws, knowledge=kn)
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            for f in _trade_frames()[:5]:
                ws.emit("trades", f)
        if calls["n"] == 2:
            ws.reconnects = 1  # the socket dropped and came back
        return calls["n"] > 3

    rec.run(should_stop=stop, sleep=lambda s: None)
    gaps = [e for e in TapeCursor().fresh_rows(vault.tape) if e.stream == "gap"]
    assert len(gaps) == 1 and gaps[0].payload["reason"] == "reconnect"
    assert gaps[0].payload["ts_from"] == rec.last_trade_ts["BTCUSDT"].isoformat()
    # the previous process's last trade is remembered in recorder_status …
    status = json.loads(kn.meta("recorder_status"))
    assert status["last_trade_ts"]["BTCUSDT"] == rec.last_trade_ts["BTCUSDT"].isoformat()
    # … so a NEW process marks the hole from there to its own start
    ws2 = FakeWs()
    rec2 = LiveRecorder(symbols=["BTCUSDT"], data_root=vault.tape, ws_factory=lambda: ws2, knowledge=kn)
    rec2.run(should_stop=lambda: True, sleep=lambda s: None)
    gaps = sorted(
        (e for e in TapeCursor().fresh_rows(vault.tape) if e.stream == "gap"),
        key=lambda e: e.payload["ts_to"],
    )
    assert [g.payload["reason"] for g in gaps] == ["reconnect", "start"]
    assert gaps[-1].payload["ts_from"] == rec.last_trade_ts["BTCUSDT"].isoformat()
    kn.close()
