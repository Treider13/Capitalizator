"""Book validation: ready, both sides, bid < ask. Does not invent levels. No size."""

from __future__ import annotations

from datetime import UTC, datetime

from capitalizator.book.reconstruct import Book
from capitalizator.book.validate import validate
from capitalizator.recorder.rest_snapshot import BookSnapshot

TS = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _ready(*, bids: tuple[tuple[str, str], ...], asks: tuple[tuple[str, str], ...]) -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(symbol="BTCUSDT", exchange_ts=TS, seq=1, bids=bids, asks=asks)
    )
    return book


def test_none_or_not_ready_is_not_ready() -> None:
    assert validate(None).ok is False
    assert validate(None).reason == "not_ready"
    assert validate(Book()).reason == "not_ready"


def test_empty_side_is_invalid() -> None:
    got = validate(_ready(bids=(("100", "1"),), asks=()))
    assert got.ok is False
    assert got.reason == "empty_side"


def test_crossed_book_is_invalid() -> None:
    got = validate(_ready(bids=(("101", "1"),), asks=(("100", "1"),)))
    assert got.ok is False
    assert got.reason == "crossed"


def test_locked_book_is_invalid() -> None:
    got = validate(_ready(bids=(("100", "1"),), asks=(("100", "1"),)))
    assert got.ok is False
    assert got.reason == "locked"


def test_one_tick_spread_is_ok() -> None:
    got = validate(_ready(bids=(("100", "1"),), asks=(("100.1", "1"),)))
    assert got.ok is True
    assert got.reason is None
