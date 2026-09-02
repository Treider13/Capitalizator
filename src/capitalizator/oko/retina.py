"""Retina — the touch window in dimensionless units. No absolute prices or sizes.

Same 8s clock as ZLG / OFI / PRS: [t0, t0 + zlg_window_s]. book_pre is the book
at the print; book_path is every ready book inside the window; trades are the
prints. Everything raw is measured in ticks, in shares of the zone-side depth,
or in the Passport's medians. A raw fact that does not exist is None.

Zone-side pressure: takers hitting the zone (sell into support, buy into
resistance). Relief: takers hitting the other side. aggression ∈ [−1, 1].
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from capitalizator.book.reconstruct import Book
from capitalizator.book.wall_watch import WallEvent
from capitalizator.oko.passport import Passport
from capitalizator.tape.classify import TapeClassifier
from capitalizator.tape.ofi import OFI
from capitalizator.types import MarketEvent, require_utc
from capitalizator.zlg.gesture import BookAdd
from capitalizator.zones.model import Zone

BookSide = str


@dataclass(frozen=True)
class RawWindow:
    """What the desk hands ОКО when the 8s clock closes. Immutable, replayable."""

    symbol: str
    zone: Zone
    t0: datetime
    window_s: int
    tick_size: Decimal
    delta_ticks: int
    book_pre: Book
    book_path: tuple[tuple[datetime, Book], ...]
    trades: tuple[MarketEvent, ...]
    adds: tuple[BookAdd, ...]
    wall_events: tuple[WallEvent, ...]

    def __post_init__(self) -> None:
        require_utc(self.t0)
        if self.window_s <= 0:
            raise ValueError("window_s must be > 0")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        if self.delta_ticks <= 0:
            raise ValueError("delta_ticks must be > 0")
        if self.zone.symbol != self.symbol:
            raise ValueError("zone symbol must match window symbol")
        if not self.book_pre.ready:
            raise ValueError("RawWindow needs a ready book_pre")
        prev = None
        for ts, book in self.book_path:
            when = require_utc(ts)
            if prev is not None and when < prev:
                raise ValueError("book_path must be time-ordered")
            prev = when
            if not book.ready:
                raise ValueError("book_path needs ready books")

    @property
    def t_end(self) -> datetime:
        return self.t0 + timedelta(seconds=self.window_s)

    @property
    def zone_side(self) -> BookSide:
        return "bid" if self.zone.side == "support" else "ask"

    @property
    def opp_side(self) -> BookSide:
        return "ask" if self.zone_side == "bid" else "bid"

    @property
    def center(self) -> Decimal:
        return (self.zone.lo + self.zone.hi) / 2

    def prints(self) -> list[MarketEvent]:
        """Prints of this symbol inside [t0, t_end]. Other streams are not prints."""
        out: list[MarketEvent] = []
        for trade in self.trades:
            if trade.stream != "trades" or trade.symbol != self.symbol:
                continue
            ts = require_utc(trade.exchange_ts)
            if self.t0 <= ts <= self.t_end:
                out.append(trade)
        return out

    def book_end(self) -> Book:
        """Last ready book in the window, else book_pre."""
        inside = [book for ts, book in self.book_path if self.t0 <= ts <= self.t_end]
        return inside[-1] if inside else self.book_pre


@dataclass(frozen=True)
class RetinaFrame:
    """Raw facts (always) and Passport-normalised facts (None until mature)."""

    n_prints: int
    spread_ticks_pre: Decimal | None
    depth_side_pre: Decimal
    depth_opp_pre: Decimal
    depth_side_end: Decimal
    depth_end_ratio: Decimal | None
    imbalance_pre: Decimal | None
    imbalance_end: Decimal | None
    ofi: Decimal | None
    ofi_rel: Decimal | None
    pressure_qty: Decimal
    relief_qty: Decimal
    aggression: Decimal | None
    max_print_qty: Decimal | None
    range_ticks: Decimal | None
    prints_per_s: Decimal
    mid_move_ticks: Decimal | None
    passport_mature: bool
    depth_side_rel: Decimal | None
    spread_z: Decimal | None
    rate_rel: Decimal | None
    max_print_rel: Decimal | None
    range_rel: Decimal | None


def frame(raw: RawWindow, passport: Passport) -> RetinaFrame:
    """One frame per touch window. Passport is read, never written here."""
    if passport.symbol != raw.symbol:
        raise ValueError("passport symbol must match window symbol")
    clf = TapeClassifier()
    center = str(raw.center)
    side, opp = raw.zone_side, raw.opp_side
    pre = raw.book_pre
    end = raw.book_end()

    depth_side_pre = pre.depth_near(side, center, raw.delta_ticks)
    depth_opp_pre = pre.depth_near(opp, center, raw.delta_ticks)
    depth_side_end = end.depth_near(side, center, raw.delta_ticks)
    depth_end_ratio = depth_side_end / depth_side_pre if depth_side_pre > 0 else None

    spread = pre.spread()
    spread_ticks = None if spread is None else spread / raw.tick_size
    imbalance_pre = pre.imbalance(5)
    imbalance_end = end.imbalance(5)

    prints = raw.prints()
    pressure = Decimal("0")
    relief = Decimal("0")
    max_print: Decimal | None = None
    pxs: list[Decimal] = []
    want_pressure = "sell" if side == "bid" else "buy"
    for trade in prints:
        qty = Decimal(str(trade.payload["qty"]))
        px = Decimal(str(trade.payload["px"]))
        if qty <= 0 or px <= 0:
            raise ValueError("print px/qty must be > 0")
        pxs.append(px)
        if clf.taker_side(trade) == want_pressure:
            pressure += qty
        else:
            relief += qty
        if max_print is None or qty > max_print:
            max_print = qty
    total = pressure + relief
    aggression = (pressure - relief) / total if total > 0 else None
    range_ticks = (max(pxs) - min(pxs)) / raw.tick_size if len(pxs) >= 2 else None
    prints_per_s = Decimal(len(prints)) / Decimal(raw.window_s)

    inside = [book for ts, book in raw.book_path if raw.t0 <= ts <= raw.t_end]
    ofi: Decimal | None = None
    if len(inside) >= 2:
        try:
            ofi = OFI().window(prints, inside)
        except ValueError:
            ofi = None
    ofi_rel = None if ofi is None or depth_side_pre <= 0 else ofi / depth_side_pre

    mid_move = _mid_move_ticks(pre, end, raw.tick_size)

    mature = passport.mature
    return RetinaFrame(
        n_prints=len(prints),
        spread_ticks_pre=spread_ticks,
        depth_side_pre=depth_side_pre,
        depth_opp_pre=depth_opp_pre,
        depth_side_end=depth_side_end,
        depth_end_ratio=depth_end_ratio,
        imbalance_pre=imbalance_pre,
        imbalance_end=imbalance_end,
        ofi=ofi,
        ofi_rel=ofi_rel,
        pressure_qty=pressure,
        relief_qty=relief,
        aggression=aggression,
        max_print_qty=max_print,
        range_ticks=range_ticks,
        prints_per_s=prints_per_s,
        mid_move_ticks=mid_move,
        passport_mature=mature,
        depth_side_rel=passport.depth.rel(depth_side_pre) if mature else None,
        spread_z=(
            passport.spread_ticks.z(spread_ticks) if mature and spread_ticks is not None else None
        ),
        rate_rel=passport.prints_per_s.rel(prints_per_s) if mature else None,
        max_print_rel=(
            passport.print_qty.rel(max_print) if mature and max_print is not None else None
        ),
        range_rel=(
            passport.range_ticks.rel(range_ticks) if mature and range_ticks is not None else None
        ),
    )


def observe_passport(raw: RawWindow, passport: Passport, frame_: RetinaFrame) -> None:
    """Append this window's raw facts. Call *after* frame() — PIT."""
    passport.observe(
        depth=frame_.depth_side_pre,
        spread_ticks=frame_.spread_ticks_pre,
        print_qtys=[Decimal(str(t.payload["qty"])) for t in raw.prints()],
        prints_per_s=frame_.prints_per_s,
        range_ticks=frame_.range_ticks,
    )


def _mid_move_ticks(pre: Book, end: Book, tick: Decimal) -> Decimal | None:
    b0, a0 = pre.best()
    b1, a1 = end.best()
    if b0 is None or a0 is None or b1 is None or a1 is None:
        return None
    return ((b1 + a1) / 2 - (b0 + a0) / 2) / tick


def levels_in_window(
    events: Sequence[WallEvent], *, since: datetime, until: datetime
) -> list[WallEvent]:
    start = require_utc(since)
    stop = require_utc(until)
    return [e for e in events if start <= require_utc(e.ts) <= stop]
