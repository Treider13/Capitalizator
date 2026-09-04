"""24/7 desk must be O(1) per event: bounded buffers, batched meta, tape cursor."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.desk.tape import TapeCursor, consume_tape
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import BufferedParquetSink, ParquetSink
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _events(n: int, per_sec: int = 20) -> list[MarketEvent]:
    out = []
    px = Decimal("100000")
    for i in range(n):
        ts = T0 + timedelta(milliseconds=i * (1000 // per_sec))
        px += Decimal("0.1") if i % 2 else Decimal("-0.1")
        out.append(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                payload={"px": str(px), "qty": "0.01", "side": "sell"},
            )
        )
        if i % 5 == 0:
            out.append(
                MarketEvent(
                    stream="book_diff",
                    exchange="bybit",
                    symbol="BTCUSDT",
                    exchange_ts=ts,
                    recv_ts=ts,
                    seq=i + 2,
                    payload={"b": [[str(px - 1), "3"]], "a": [[str(px + 1), "3"]]},
                )
            )
    return out


def _desk(tmp_path: Path) -> DeskLoop:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=T0,
            recv_ts=T0,
            seq=1,
            payload={"bids": [["99999", "5"]], "asks": [["100001", "5"]]},
        )
    )
    return desk


def test_per_event_cost_does_not_grow_with_tape_length(tmp_path: Path) -> None:
    """Old loop: 2k→4k→8k prints took 11s→44s→175s (quadratic). Now ~linear."""
    costs = []
    for n in (1500, 3000):
        desk = _desk(tmp_path / str(n))
        evs = _events(n)
        t = time.perf_counter()
        desk.play(evs)
        costs.append((time.perf_counter() - t) / len(evs))
    # doubling the tape must not double the per-event cost (allow 1.6x jitter)
    assert costs[1] < costs[0] * 1.6, costs


def test_buffers_are_bounded_by_time_window(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    evs = _events(3000, per_sec=2)  # 25 minutes of tape > 20 min keep window
    desk.play(evs)
    st = desk.state_for("BTCUSDT")
    keep = desk._trade_keep_window()
    assert st.trades_dropped > 0
    assert len(st.trades) < 3000
    assert st.trades[0].exchange_ts >= evs[-1].exchange_ts - keep
    assert [b.tf for b in st.bars].count("15m") == 1
    assert len(st.book_history) <= 40  # 8 s window at 2 diffs/s
    wall = desk.walls["BTCUSDT"]
    assert all(e.ts >= evs[-1].exchange_ts - wall.max_age for e in wall.events)


def test_resync_with_levels_rebuilds_the_book_instead_of_wiping(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    assert desk.state_for("BTCUSDT").book.ready
    out = desk.on_event(
        MarketEvent(
            stream="resync",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=T0,
            recv_ts=T0,
            seq=500,
            payload={"update_id": 500, "bids": [["99990", "2"]], "asks": [["100010", "2"]]},
        )
    )
    assert out == [{"event": "resync", "symbol": "BTCUSDT", "book_dirty": False}]
    book = desk.state_for("BTCUSDT").book
    assert book.ready and book.best() == (Decimal("99990"), Decimal("100010")) and book.seq == 500
    bare = desk.on_event(
        MarketEvent(stream="gap", exchange="bybit", symbol="BTCUSDT", exchange_ts=T0, recv_ts=T0,
                    payload={})
    )
    assert bare[0]["book_dirty"] is True and not desk.state_for("BTCUSDT").book.ready


def test_trades_do_not_starve_ui_book(tmp_path: Path) -> None:
    """Serve ticks first, then BTC prints own the 0.5s flush. Book must still land.

    Live Chronos showed ZLG RETREAT (RAM book) and `book:BTCUSDT` missing — the
    trade path flushed last_price and never queued depth. Bybit keeps orderbook
    on its own WS (L50 ~20ms); the UI tick is last-value of both streams.
    """
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
    desk.tick(T0)
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=T0 + timedelta(milliseconds=100),
            recv_ts=T0 + timedelta(milliseconds=100),
            seq=1,
            payload={"bids": [["99999", "5"]], "asks": [["100001", "5"]]},
        )
    )
    assert desk.state_for("BTCUSDT").book.ready
    for i in range(40):
        ts = T0 + timedelta(milliseconds=200 + 20 * i)
        desk.on_trade(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                payload={"px": str(Decimal("100000") + i), "qty": "0.01", "side": "buy"},
            ),
            [],
        )
    got = desk.knowledge.book_levels("BTCUSDT")
    assert got is not None
    assert got["bids"][0] == ["99999", "5"]
    assert got["asks"][0] == ["100001", "5"]
    later = T0 + timedelta(seconds=2)
    desk.on_event(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=later,
            recv_ts=later,
            seq=2,
            payload={"b": [["100050", "9"]], "a": [["100060", "8"]]},
        )
    )
    desk.tick(later + timedelta(seconds=1))
    got = desk.knowledge.book_levels("BTCUSDT")
    assert got is not None
    assert got["bids"][0] == ["100050", "9"]
    assert got["asks"][0] == ["100001", "5"]
    assert ["100060", "8"] in got["asks"]


def test_gap_clears_ui_book_instead_of_leaving_stale_levels(tmp_path: Path) -> None:
    """Bybit: new snapshot / u=1 restart resets the local book. Stale L2 on Chronos is a lie."""
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")
    desk.on_event(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=T0,
            recv_ts=T0,
            seq=1,
            payload={"bids": [["99999", "5"]], "asks": [["100001", "5"]]},
        )
    )
    desk.tick(T0 + timedelta(seconds=1))
    assert desk.knowledge.book_levels("BTCUSDT")["bids"][0] == ["99999", "5"]
    desk.on_event(
        MarketEvent(
            stream="gap",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=T0 + timedelta(seconds=2),
            recv_ts=T0 + timedelta(seconds=2),
            payload={},
        )
    )
    assert not desk.state_for("BTCUSDT").book.ready
    desk.tick(T0 + timedelta(seconds=3))
    got = desk.knowledge.book_levels("BTCUSDT")
    assert got == {"symbol": "BTCUSDT", "bids": [], "asks": [], "ts": None}


def test_meta_writes_are_batched_not_per_print(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    kn = desk.knowledge
    writes = {"n": 0}
    orig = kn.set_meta_many

    def counting(rows):
        writes["n"] += 1
        return orig(rows)

    kn.set_meta_many = counting  # type: ignore[method-assign]
    evs = _events(400)  # 20 s of tape → at most ~40 flushes at 0.5 s cadence
    desk.play(evs)
    assert writes["n"] <= 60, writes
    desk.tick(evs[-1].exchange_ts + timedelta(seconds=1))
    assert kn.last_prices()["BTCUSDT"] == str(desk.last_price["BTCUSDT"])
    assert kn.book_levels("BTCUSDT") is not None


def test_buffered_sink_writes_immutable_parts_readable_by_cursor(tmp_path: Path) -> None:
    root = tmp_path / "tape"
    root.mkdir()
    sink = BufferedParquetSink(root, flush_every_s=1.0, max_rows=100)
    evs = _events(250)
    for e in evs:
        sink.write(e)
    assert sink.parts_written >= 2  # max_rows flushes
    sink.flush()
    assert sink.pending() == 0
    assert sink.flushed_count == len(evs)
    parts = sorted(root.rglob("*.parquet"))
    assert len(parts) == sink.parts_written
    assert all(".0000" in p.name for p in parts)
    # the legacy single-file sink still works next to parts
    ParquetSink(root).write(evs[0])
    cursor = TapeCursor()
    first = cursor.fresh_rows(root)
    assert len(first) == len(evs) + 1
    # second pass with nothing new reads no file at all
    read_before = cursor.files_read
    assert cursor.fresh_rows(root) == []
    assert cursor.files_read == read_before


def test_consume_tape_with_cursor_only_parses_changed_files(tmp_path: Path) -> None:
    root = tmp_path / "tape"
    root.mkdir()
    sink = BufferedParquetSink(root, max_rows=10_000)
    evs = _events(60)
    for e in evs[:30]:
        sink.write(e)
    sink.flush()
    desk = _desk(tmp_path)
    seen: set = set()
    cursor = TapeCursor()
    n1 = consume_tape(desk, root, seen=seen, cursor=cursor, now=evs[29].exchange_ts)
    assert n1 == len([e for e in evs[:30]])
    n2 = consume_tape(desk, root, seen=seen, cursor=cursor, now=evs[29].exchange_ts)
    assert n2 == 0
    for e in evs[30:]:
        sink.write(e)
    sink.flush()
    n3 = consume_tape(desk, root, seen=seen, cursor=cursor, now=evs[-1].exchange_ts)
    assert n3 == len(evs[30:])
    assert cursor.files_read == 4  # 2 streams x 2 flushes, each read once
