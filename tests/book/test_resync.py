"""0.2.4 — synthetic gap → stream=resync, book equals the REST snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.book.reconstruct import Book, BookDirty
from capitalizator.book.resync import BookResync
from capitalizator.recorder.rest_snapshot import BookSnapshot, RestSnapshot
from capitalizator.recorder.ws_book import BybitBookWs

RECV = datetime(2026, 8, 30, 13, 31, tzinfo=UTC)


def _snap(u: int, bid: str = "100", bid_sz: str = "1", ask: str = "101", ask_sz: str = "1") -> BookSnapshot:
    return BookSnapshot(
        symbol="BTCUSDT",
        exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
        seq=u,
        bids=((bid, bid_sz),),
        asks=((ask, ask_sz),),
        cross_seq=u * 10,
    )


def test_gap_emits_resync_and_book_matches_snapshot() -> None:
    rest_snap = _snap(50, bid="65485.47", bid_sz="47.081829", ask="65557.7", ask_sz="16.606555")
    book = Book()
    book.apply_snapshot(_snap(10))
    rs = BookResync(book, lambda: rest_snap, symbol="BTCUSDT")
    stale = _snap(20)  # u 10 → 20 is a hole
    events = rs.feed("delta", stale, recv_ts=RECV)
    assert len(events) == 1
    assert events[0].stream == "resync"
    assert events[0].seq == 50
    assert rs.events[-1].stream == "resync"
    expected = Book()
    expected.apply_snapshot(rest_snap)
    assert book.fingerprint() == expected.fingerprint()
    assert book.seq == 50
    assert book.level("bid", "65485.47") == Decimal("47.081829")


def test_failed_delta_is_not_applied_on_top_of_snapshot() -> None:
    rest_snap = _snap(80, bid="200", bid_sz="9")
    book = Book()
    book.apply_snapshot(_snap(1))
    rs = BookResync(book, lambda: rest_snap, symbol="BTCUSDT")
    poison = _snap(9, bid="999", bid_sz="99")
    rs.feed("delta", poison, recv_ts=RECV)
    assert book.level("bid", "999") == 0
    assert book.level("bid", "200") != 0


def test_contiguous_diff_does_not_resync() -> None:
    book = Book()
    book.apply_snapshot(_snap(10))
    rs = BookResync(book, lambda: _snap(99), symbol="BTCUSDT")
    nxt = BookSnapshot(
        symbol="BTCUSDT",
        exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
        seq=11,
        bids=(("100", "2"),),
        asks=(),
    )
    assert rs.feed("delta", nxt, recv_ts=RECV) == []
    assert book.seq == 11
    assert rs.events == []


def test_on_gap_uses_rest_parser_shape() -> None:
    official = {
        "retCode": 0,
        "result": {
            "s": "BTCUSDT",
            "a": [["65557.7", "16.606555"]],
            "b": [["65485.47", "47.081829"]],
            "ts": 1716863719031,
            "u": 230704,
            "seq": 1432604333,
        },
    }
    book = Book()
    book.apply_snapshot(_snap(1))
    parsed = RestSnapshot().parse(official)
    rs = BookResync(book, lambda: parsed, symbol="BTCUSDT")
    event = rs.on_gap(recv_ts=RECV)
    assert event.stream == "resync"
    assert event.payload["update_id"] == 230704
    assert event.payload["cross_seq"] == 1432604333
    assert book.seq == 230704


def _frame(kind: str, u: int, bid: str = "100", bid_sz: str = "1") -> dict:
    return {
        "topic": "orderbook.200.BTCUSDT",
        "type": kind,
        "ts": 1725024600000,
        "data": {
            "s": "BTCUSDT",
            "u": u,
            "seq": u * 10,
            "b": [[bid, bid_sz]],
            "a": [["101", "1"]],
        },
    }


def test_ws_ingest_without_fetch_still_raises_on_gap() -> None:
    ws = BybitBookWs()
    ws.ingest_frames([_frame("snapshot", 10)], recv_ts=RECV)
    with pytest.raises(BookDirty, match="gap"):
        ws.ingest_frames([_frame("delta", 20, bid="999", bid_sz="99")], recv_ts=RECV)
    assert ws.book.seq == 10
    assert ws.book.level("bid", "999") == 0


def test_ws_ingest_with_fetch_resyncs_and_drops_poison() -> None:
    rest = _snap(50, bid="65485.47", bid_sz="47.081829")
    ws = BybitBookWs(fetch_snapshot=lambda: rest)
    events = ws.ingest_frames(
        [_frame("snapshot", 10), _frame("delta", 20, bid="999", bid_sz="99")],
        recv_ts=RECV,
    )
    streams = [e.stream for e in events]
    assert "resync" in streams
    assert "book_diff" not in streams
    assert ws.book.seq == 50
    assert ws.book.level("bid", "999") == 0
    assert ws.book.level("bid", "65485.47") != 0
