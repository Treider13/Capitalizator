"""0.2.5 — 50 BTC @ 60000: pull vs eaten. Wall is not an entry."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.book.reconstruct import Book
from capitalizator.book.wall_watch import WallWatch
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import MarketEvent

TS = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _book(bid_sz: str, *, u: int = 1) -> Book:
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=TS,
            seq=u,
            bids=(("60000", bid_sz), ("59999", "1")),
            asks=(("60001", "1"),),
        )
    )
    return book


def _sell(qty: str) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=TS,
        recv_ts=TS,
        seq=1,
        payload={"px": "60000", "qty": qty, "side": "sell"},
    )


def test_wall_appeared_then_pulled() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = _book("50")
    ev = watch.on_book_and_trade(book, ts=TS)
    assert [e.kind for e in ev] == ["appeared"]
    assert ev[0].px == "60000"
    assert ev[0].side == "bid"
    assert ev[0].size == Decimal("50")
    gone = Book()
    gone.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=TS,
            seq=2,
            bids=(("59999", "1"),),
            asks=(("60001", "1"),),
        )
    )
    ev2 = watch.on_book_and_trade(gone, ts=TS)
    assert [e.kind for e in ev2] == ["pulled"]
    assert watch.events[-1].kind == "pulled"


def test_wall_eaten_by_tape() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = _book("50")
    assert watch.on_book_and_trade(book, ts=TS)[0].kind == "appeared"
    watch.on_book_and_trade(book, _sell("20"), ts=TS)
    watch.on_book_and_trade(book, _sell("30"), ts=TS)
    gone = Book()
    gone.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=TS,
            seq=3,
            bids=(("59999", "1"),),
            asks=(("60001", "1"),),
        )
    )
    ev = watch.on_book_and_trade(gone, ts=TS)
    assert [e.kind for e in ev] == ["eaten"]
    assert ev[0].px == "60000"


def test_partial_prints_then_cancel_is_pulled() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = _book("50")
    watch.on_book_and_trade(book, ts=TS)
    watch.on_book_and_trade(book, _sell("10"), ts=TS)
    gone = Book()
    gone.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=TS,
            seq=4,
            bids=(("59999", "1"),),
            asks=(("60001", "1"),),
        )
    )
    ev = watch.on_book_and_trade(gone, ts=TS)
    assert [e.kind for e in ev] == ["pulled"]


def test_not_ready_book_emits_nothing() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    assert watch.on_book_and_trade(Book(), ts=TS) == []


def test_small_level_is_not_a_wall() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = _book("1")
    assert watch.on_book_and_trade(book, ts=TS) == []
