"""0.2.5 — 50 BTC @ 60000: pull vs eaten. Wall is not an entry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.book.wall_watch import (
    WallEvent,
    WallWatch,
    last_wall_kind,
    pulled_without_print,
)
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


def test_naive_ts_is_rejected() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    with pytest.raises(TypeError, match="naive"):
        watch.on_book_and_trade(_book("50"), ts=datetime(2026, 8, 30, 16, 30))


def test_not_ready_book_emits_nothing() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    assert watch.on_book_and_trade(Book(), ts=TS) == []


def test_small_level_is_not_a_wall() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = _book("1")
    assert watch.on_book_and_trade(book, ts=TS) == []


def _wall(kind: str, ts: datetime) -> WallEvent:
    return WallEvent(
        symbol="BTCUSDT",
        px="60000",
        side="bid",
        size=Decimal("50"),
        kind=kind,  # type: ignore[arg-type]
        ts=ts,
    )


def test_stale_pull_is_not_this_touch() -> None:
    old = _wall("pulled", TS - timedelta(hours=1))
    assert pulled_without_print((old,), since=TS) is False


def test_pull_then_appear_in_window_still_counts() -> None:
    """Last-event-only would hide the pull. Law 5 is the pull, not the later size."""
    pulled = _wall("pulled", TS)
    appeared = _wall("appeared", TS + timedelta(seconds=1))
    assert pulled_without_print((pulled, appeared), since=TS) is True


def test_empty_wall_history_is_false() -> None:
    assert pulled_without_print((), since=TS) is False


def test_last_wall_kind_ignores_stale_and_keeps_window() -> None:
    old = _wall("pulled", TS - timedelta(hours=1))
    appeared = _wall("appeared", TS)
    pulled = _wall("pulled", TS + timedelta(seconds=1))
    assert last_wall_kind((old,), since=TS) is None
    assert last_wall_kind((old, appeared, pulled), since=TS) == "pulled"
    assert last_wall_kind((), since=TS) is None
