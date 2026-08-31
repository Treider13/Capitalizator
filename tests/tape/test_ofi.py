"""CKS OFI from consecutive books. Flipping tape side must not change the number."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.tape.ofi import OFI
from capitalizator.types import MarketEvent

TS = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _book(*, bid: str, bid_sz: str, ask: str = "101", ask_sz: str = "5", u: int = 1) -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=TS,
            seq=u,
            bids=((bid, bid_sz),),
            asks=((ask, ask_sz),),
        )
    )
    return book


def _trade(side: str) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=TS,
        recv_ts=TS,
        seq=None,
        payload={"px": "100", "qty": "99", "side": side},
    )


def test_same_prices_size_up_on_bid() -> None:
    """Bid 5→8, ask unchanged: e_n = +8 − 5 − 5 + 5 = +3."""
    prev = _book(bid="100", bid_sz="5")
    curr = _book(bid="100", bid_sz="8", u=2)
    assert OFI().window([_trade("sell")], [prev, curr]) == Decimal("3")


def test_tape_side_does_not_change_ofi() -> None:
    prev = _book(bid="100", bid_sz="5")
    curr = _book(bid="100", bid_sz="8", u=2)
    buys = OFI().window([_trade("buy")], [prev, curr])
    sells = OFI().window([_trade("sell")], [prev, curr])
    assert buys == sells == Decimal("3")


def test_one_book_is_error() -> None:
    with pytest.raises(ValueError, match="≥2"):
        OFI().window([], [_book(bid="100", bid_sz="5")])


def test_not_ready_is_error() -> None:
    ready = _book(bid="100", bid_sz="5")
    with pytest.raises(ValueError, match="ready"):
        OFI().window([], [ready, Book()])
