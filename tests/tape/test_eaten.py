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


def test_gap_in_window_is_not_a_taker() -> None:
    """A seq-gap noticed in the 8s window is not a print. Do not abort eaten."""
    clf = TapeClassifier()
    book = _book(bid_sz="10")
    gap = MarketEvent(
        stream="gap",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=PRINT,
        recv_ts=PRINT + timedelta(seconds=1),
        seq=None,
        payload={"ts_from": PRINT.isoformat(), "ts_to": (PRINT + timedelta(seconds=1)).isoformat()},
    )
    assert clf.eaten(
        book=book,
        trades=[_sell("1"), gap],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is False
    assert clf.eaten(
        book=book,
        trades=[_sell("6"), gap],
        zone=ZONE,
        t0=PRINT,
        tick_size=TICK,
    ) is True


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


def test_fill_tape_touch_id_leaves_other_unlabeled() -> None:
    later = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("101"),
        hi=Decimal("101.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    reg = Registry(tick_size=TICK)
    first = reg.on_trade(
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
    second = reg.on_trade(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=PRINT + timedelta(seconds=30),
            recv_ts=PRINT + timedelta(seconds=30),
            seq=None,
            payload={"px": "101.1", "qty": "6", "side": "sell"},
        ),
        [ZONE, later],
    )
    assert len(first) == 1
    assert len(second) == 1
    with pytest.raises(ValueError, match="touch_id"):
        reg.fill_tape(book=_book(bid_sz="10"), trades=[_sell("6")])
    assert reg.touches[0].tape_eaten is None
    assert reg.touches[1].tape_eaten is None
    with pytest.raises(KeyError):
        reg.fill_tape(book=_book(bid_sz="10"), trades=[_sell("6")], touch_id="missing")
    changed = reg.fill_tape(
        book=_book(bid_sz="10"),
        trades=[_sell("6")],
        touch_id=first[0].touch_id,
    )
    assert changed[0].tape_eaten is True
    assert reg.touches[0].tape_eaten is True
    assert reg.touches[1].tape_eaten is None
