"""REST resync is Hummingbot-style: fetch a snapshot when we have no book yet.

A skipped `u` on orderbook.200 is not that — CCXT applies the delta.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.book.reconstruct import Book
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


def test_u_hole_is_applied_not_resync() -> None:
    rest_snap = _snap(50, bid="65485.47", bid_sz="47.081829", ask="65557.7", ask_sz="16.606555")
    book = Book()
    book.apply_snapshot(_snap(10))
    rs = BookResync(book, lambda: rest_snap, symbol="BTCUSDT")
    nxt = _snap(20, bid="110", bid_sz="2")
    events = rs.feed("delta", nxt, recv_ts=RECV)
    assert events == []
    assert book.seq == 20
    assert book.level("bid", "110") == Decimal("2")
    assert book.level("bid", "100") == Decimal("1")


def test_diff_before_snapshot_fetches_rest() -> None:
    rest_ts = datetime(2026, 8, 30, 13, 40, tzinfo=UTC)
    rest_snap = BookSnapshot(
        symbol="BTCUSDT",
        exchange_ts=rest_ts,
        seq=50,
        bids=(("200", "1"),),
        asks=(("201", "1"),),
    )
    book = Book()
    rs = BookResync(book, lambda: rest_snap, symbol="BTCUSDT")
    poison = BookSnapshot(
        symbol="BTCUSDT",
        exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
        seq=20,
        bids=(("999", "99"),),
        asks=(("1000", "1"),),
    )
    events = rs.feed("delta", poison, recv_ts=RECV)
    assert events[0].stream == "resync"
    assert events[0].exchange_ts == rest_ts
    assert book.seq == 50
    assert book.level("bid", "999") == 0
    assert book.level("bid", "200") != 0


def test_stale_u_is_not_applied_and_does_not_resync() -> None:
    rest_snap = _snap(80, bid="200", bid_sz="9")
    book = Book()
    book.apply_snapshot(_snap(10))
    rs = BookResync(book, lambda: rest_snap, symbol="BTCUSDT")
    stale = _snap(9, bid="999", bid_sz="99")
    assert rs.feed("delta", stale, recv_ts=RECV) == []
    assert book.level("bid", "999") == 0
    assert book.seq == 10


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


def test_ws_ingest_applies_u_hole_without_inventing_a_wipe() -> None:
    ws = BybitBookWs()
    ws.ingest_frames([_frame("snapshot", 10)], recv_ts=RECV)
    ws.ingest_frames([_frame("delta", 20, bid="999", bid_sz="99")], recv_ts=RECV)
    assert ws.book.seq == 20
    assert ws.book.level("bid", "999") == Decimal("99")
    assert ws.book.level("bid", "100") == Decimal("1")


def test_ws_ingest_with_fetch_does_not_resync_a_u_hole() -> None:
    rest = _snap(50, bid="65485.47", bid_sz="47.081829")
    ws = BybitBookWs(fetch_snapshot=lambda: rest)
    events = ws.ingest_frames(
        [_frame("snapshot", 10), _frame("delta", 20, bid="999", bid_sz="99")],
        recv_ts=RECV,
    )
    assert "resync" not in [e.stream for e in events]
    assert ws.book.seq == 20
    assert ws.book.level("bid", "999") == Decimal("99")
