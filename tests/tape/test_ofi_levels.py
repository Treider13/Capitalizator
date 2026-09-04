"""Multi-level CKS OFI. L1 stays the existing number. Deeper levels add their own e_n.

A missing deeper level is skipped, not invented. levels=1 equals OFI.window today.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.tape.ofi import OFI
from capitalizator.types import MarketEvent

TS = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _book(bids: tuple[tuple[str, str], ...], asks: tuple[tuple[str, str], ...], *, u: int) -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(symbol="BTCUSDT", exchange_ts=TS, seq=u, bids=bids, asks=asks)
    )
    return book


def _trade() -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=TS,
        recv_ts=TS,
        payload={"px": "100", "qty": "1", "side": "buy"},
    )


def test_levels_one_equals_best_only() -> None:
    prev = _book((("100", "5"), ("99.9", "4")), (("101", "5"), ("101.1", "4")), u=1)
    curr = _book((("100", "8"), ("99.9", "4")), (("101", "5"), ("101.1", "4")), u=2)
    ofi = OFI()
    assert ofi.window([_trade()], [prev, curr]) == Decimal("3")
    assert ofi.window([_trade()], [prev, curr], levels=1) == Decimal("3")


def test_deeper_level_size_change_is_not_in_l1() -> None:
    """L2 bid 4→7, L1 unchanged: L1 e_n = 0, L2 e_n = +3."""
    prev = _book((("100", "5"), ("99.9", "4")), (("101", "5"), ("101.1", "4")), u=1)
    curr = _book((("100", "5"), ("99.9", "7")), (("101", "5"), ("101.1", "4")), u=2)
    ofi = OFI()
    assert ofi.window([_trade()], [prev, curr], levels=1) == Decimal("0")
    assert ofi.window([_trade()], [prev, curr], levels=2) == Decimal("3")


def test_missing_deeper_level_is_skipped() -> None:
    prev = _book((("100", "5"),), (("101", "5"),), u=1)
    curr = _book((("100", "8"),), (("101", "5"),), u=2)
    ofi = OFI()
    assert ofi.window([_trade()], [prev, curr], levels=5) == Decimal("3")


def test_levels_must_be_at_least_one() -> None:
    prev = _book((("100", "5"),), (("101", "5"),), u=1)
    curr = _book((("100", "8"),), (("101", "5"),), u=2)
    with pytest.raises(ValueError, match="levels"):
        OFI().window([_trade()], [prev, curr], levels=0)
