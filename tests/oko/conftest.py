"""Shared window builders for ОКО tests. Support zone 100–101, tick 0.1, 8s clock."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.book.wall_watch import WallEvent
from capitalizator.oko.passport import MATURE_N, Passport
from capitalizator.oko.retina import RawWindow
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import MarketEvent
from capitalizator.zlg.gesture import BookAdd
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
DELTA_TICKS = 5
WINDOW_S = 8
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
T0 = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
SUPPORT = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)
RESISTANCE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="resistance",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def make_book(
    bids: Sequence[tuple[str, str]] = (("100.4", "10"), ("100.3", "10")),
    asks: Sequence[tuple[str, str]] = (("100.6", "10"), ("100.7", "10")),
    *,
    seq: int = 1,
    ts: datetime = T0,
) -> Book:
    book = Book(tick_size=str(TICK))
    book.apply_snapshot(
        BookSnapshot(symbol="BTCUSDT", exchange_ts=ts, seq=seq, bids=tuple(bids), asks=tuple(asks))
    )
    return book


def make_trade(
    ts: datetime, *, px: str = "100.4", qty: str = "1", side: str = "sell"
) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": qty, "side": side},
    )


def make_window(
    *,
    zone: Zone = SUPPORT,
    book_pre: Book | None = None,
    path: Sequence[tuple[datetime, Book]] | None = None,
    trades: Sequence[MarketEvent] = (),
    adds: Sequence[BookAdd] = (),
    walls: Sequence[WallEvent] = (),
    t0: datetime = T0,
    oi_path: Sequence[tuple[datetime, Decimal]] = (),
    liquidations: Sequence[MarketEvent] = (),
    funding: Decimal | None = None,
) -> RawWindow:
    pre = book_pre if book_pre is not None else make_book()
    if path is None:
        path = ((t0 + timedelta(seconds=WINDOW_S), pre.snapshot_copy()),)
    return RawWindow(
        symbol="BTCUSDT",
        zone=zone,
        t0=t0,
        window_s=WINDOW_S,
        tick_size=TICK,
        delta_ticks=DELTA_TICKS,
        book_pre=pre,
        book_path=tuple(path),
        trades=tuple(trades),
        adds=tuple(adds),
        wall_events=tuple(walls),
        oi_path=tuple(oi_path),
        liquidations=tuple(liquidations),
        funding=funding,
    )


def quiet_prints(t0: datetime = T0, n: int = 4) -> list[MarketEvent]:
    """A few small mixed prints inside the window. Not a cascade, not a wash."""
    out: list[MarketEvent] = []
    for i in range(n):
        out.append(
            make_trade(
                t0 + timedelta(seconds=1 + i),
                px="100.4" if i % 2 == 0 else "100.6",
                qty=str(Decimal("0.5") + Decimal(i) / 10),
                side="sell" if i % 2 == 0 else "buy",
            )
        )
    return out


def mature_passport(
    *,
    depth: str = "20",
    spread_ticks: str = "2",
    print_qty: str = "0.5",
    prints_per_s: str = "0.5",
    range_ticks: str = "2",
    n: int = MATURE_N,
) -> Passport:
    passport = Passport("BTCUSDT")
    for _ in range(n):
        passport.observe(
            depth=Decimal(depth),
            spread_ticks=Decimal(spread_ticks),
            print_qtys=[Decimal(print_qty)],
            prints_per_s=Decimal(prints_per_s),
            range_ticks=Decimal(range_ticks),
        )
    assert passport.mature
    return passport


@pytest.fixture
def clean_window() -> RawWindow:
    return make_window(trades=quiet_prints())
