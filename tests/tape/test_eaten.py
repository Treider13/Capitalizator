"""tape_eaten: takers lifted ≥50% of depth_near on the zone side.

PHASE-BUILD glossary. No book → error, not False.
Wall with no prints in the band is not eaten.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.memory.registry import Registry
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.tape.classify import TapeClassifier
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _book(*, bid_sz: str) -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=PRINT,
            seq=1,
            bids=(("100.1", bid_sz), ("99.9", "1")),
            asks=(("100.3", "1"),),
        )
    )
    return book


def _sell(qty: str, *, ts: datetime = PRINT, px: str = "100.1") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": px, "qty": qty, "side": "sell"},
    )


def test_half_depth_taken_is_eaten() -> None:
    """depth_near(bid, zone mid, 5 ticks): 10 at 100.1 + 1 at 99.9 = 11. 50% = 5.5."""
    clf = TapeClassifier()
    book = _book(bid_sz="10")
    assert clf.eaten(
        book=book,
        trades=[_sell("6")],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is True


def test_small_print_is_not_eaten() -> None:
    clf = TapeClassifier()
    book = _book(bid_sz="10")
    assert clf.eaten(
        book=book,
        trades=[_sell("1")],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is False


def test_wall_without_prints_is_not_eaten() -> None:
    clf = TapeClassifier()
    book = _book(bid_sz="50")
    assert clf.eaten(
        book=book,
        trades=[],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is False


def test_print_outside_window_does_not_count() -> None:
    clf = TapeClassifier()
    book = _book(bid_sz="10")
    late = _sell("20", ts=PRINT + timedelta(seconds=9))
    assert clf.eaten(
        book=book,
        trades=[late],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is False


def test_not_ready_book_is_error() -> None:
    with pytest.raises(ValueError, match="ready"):
        TapeClassifier().eaten(
            book=Book(),
            trades=[],
            zone=ZONE,
            t0=PRINT,
            tick_size=TICK,
        )


def test_other_symbol_print_does_not_eat() -> None:
    clf = TapeClassifier()
    book = _book(bid_sz="10")
    eth = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="ETHUSDT",
        exchange_ts=PRINT,
        recv_ts=PRINT,
        seq=None,
        payload={"px": "100.1", "qty": "20", "side": "sell"},
    )
    assert clf.eaten(
        book=book,
        trades=[eth],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is False


def test_registry_fill_tape_is_deterministic() -> None:
    book = _book(bid_sz="10")
    trades = [_sell("6")]

    def run() -> bool:
        reg = Registry(tick_size=TICK)
        opened = reg.on_trade(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=PRINT,
                recv_ts=PRINT,
                seq=None,
                payload={"px": "100.1", "qty": "6", "side": "sell"},
            ),
            [ZONE],
        )
        assert opened[0].tape_eaten is None
        reg.fill_tape(book=book, trades=trades)
        return reg.touches[0].tape_eaten is True

    assert run() is True
    assert run() == run()
