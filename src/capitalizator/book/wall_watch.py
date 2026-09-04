"""0.2.5 — wall appeared / pulled / eaten. Events only, never an entry.

A wall is one price whose size ≥ min_size (fixture: 50 BTC @ 60000).
- appeared: level crossed the threshold
- pulled: level left without prints covering the last size
- eaten: tape at that price covered the last size, then the level left

Not a support. Not a spoof classifier (needs our 24h data).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from capitalizator.book.reconstruct import Book, _canon
from capitalizator.types import MarketEvent, require_utc

WallKind = Literal["appeared", "pulled", "eaten"]
WallSide = Literal["bid", "ask"]


@dataclass(frozen=True)
class WallEvent:
    symbol: str
    px: str
    side: WallSide
    size: Decimal
    kind: WallKind
    ts: datetime


@dataclass
class _Tracked:
    size: Decimal
    printed: Decimal = Decimal("0")


def pulled_without_print(
    events: Sequence[WallEvent],
    *,
    since: datetime,
    until: datetime | None = None,
) -> bool:
    """A wall left without tape covering its size in [since, until].

    Last-event-only is wrong: events are never trimmed, so a pull hours ago
    would veto every later bounce, and an appear after a pull would hide it.
    An open end is also wrong: a pull after the 8s touch clock is another event.
    Sitting size ≥ min_size is normal book, not this flag (0.2.5 = pulled).
    """
    start = require_utc(since)
    end = require_utc(until) if until is not None else None
    return any(
        event.kind == "pulled"
        and event.ts >= start
        and (end is None or event.ts <= end)
        for event in events
    )


def last_wall_kind(
    events: Sequence[WallEvent],
    *,
    since: datetime,
    until: datetime | None = None,
) -> WallKind | None:
    """Last wall event in the same window as pulled_without_print. Else None."""
    start = require_utc(since)
    end = require_utc(until) if until is not None else None
    in_window = [
        event
        for event in events
        if event.ts >= start and (end is None or event.ts <= end)
    ]
    return in_window[-1].kind if in_window else None


class WallWatch:
    # Wall events are read in a ±zlg_window_s (8s) window around a touch and the
    # journal stamps the last kind in that window. One hour is a generous bound.
    MAX_AGE = timedelta(hours=1)

    def __init__(
        self,
        symbol: str,
        *,
        min_size: Decimal | None,
        max_age: timedelta | None = None,
    ) -> None:
        if min_size is not None and min_size <= 0:
            raise ValueError("min_size must be > 0")
        self.symbol = symbol
        # None = no norm for this symbol yet: nothing is a wall, nothing is a pull.
        self.min_size = min_size
        self._walls: dict[tuple[WallSide, Decimal], _Tracked] = {}
        self.events: list[WallEvent] = []
        self.max_age = max_age if max_age is not None else self.MAX_AGE
        self.trimmed = 0

    def set_min_size(self, min_size: Decimal | None) -> None:
        """Move the threshold with the symbol's norm. Levels that stop qualifying are
        forgotten silently — a threshold change is not a wall being pulled."""
        if min_size is not None and min_size <= 0:
            raise ValueError("min_size must be > 0")
        if min_size == self.min_size:
            return
        self.min_size = min_size
        if min_size is None:
            self._walls.clear()
            return
        for key in [k for k, tracked in self._walls.items() if tracked.size < min_size]:
            del self._walls[key]

    def tracked_count(self) -> int:
        return len(self._walls)

    def trim(self, now: datetime) -> int:
        """Drop events older than max_age. Bounded memory for a 24/7 desk."""
        cutoff = require_utc(now) - self.max_age
        drop = 0
        for event in self.events:
            if event.ts >= cutoff:
                break
            drop += 1
        if drop:
            del self.events[:drop]
            self.trimmed += drop
        return drop

    def on_book_and_trade(
        self,
        book: Book,
        trade: MarketEvent | None = None,
        *,
        ts: datetime,
    ) -> list[WallEvent]:
        when = require_utc(ts)
        if not book.ready or self.min_size is None:
            return []
        if trade is not None:
            self._on_trade(trade)
        out = self._on_book(book, when)
        self.events.extend(out)
        self.trim(when)
        return out

    def _on_trade(self, trade: MarketEvent) -> None:
        px = Decimal(str(trade.payload["px"]))
        qty = Decimal(str(trade.payload["qty"]))
        taker = str(trade.payload["side"])
        side: WallSide = "ask" if taker == "buy" else "bid"
        tracked = self._walls.get((side, px))
        if tracked is not None:
            tracked.printed += qty

    def _on_book(self, book: Book, when: datetime) -> list[WallEvent]:
        out: list[WallEvent] = []
        current: dict[tuple[WallSide, Decimal], Decimal] = {}
        threshold = self.min_size
        assert threshold is not None
        for side in ("bid", "ask"):
            for px, sz in book.levels(side).items():
                if sz >= threshold:
                    current[(side, px)] = sz
        for key, sz in current.items():
            if key not in self._walls:
                self._walls[key] = _Tracked(size=sz)
                out.append(
                    WallEvent(
                        symbol=self.symbol,
                        px=_canon(key[1]),
                        side=key[0],
                        size=sz,
                        kind="appeared",
                        ts=when,
                    )
                )
            else:
                self._walls[key].size = sz
        gone = [key for key in self._walls if key not in current]
        for key in gone:
            tracked = self._walls.pop(key)
            kind: WallKind = "eaten" if tracked.printed >= tracked.size else "pulled"
            out.append(
                WallEvent(
                    symbol=self.symbol,
                    px=_canon(key[1]),
                    side=key[0],
                    size=tracked.size,
                    kind=kind,
                    ts=when,
                )
            )
        return out
