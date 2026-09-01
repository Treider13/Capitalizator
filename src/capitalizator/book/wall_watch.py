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
from datetime import datetime
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


def pulled_without_print(events: Sequence[WallEvent], *, since: datetime) -> bool:
    """A wall left without tape covering its size at/after `since`.

    Last-event-only is wrong: events are never trimmed, so a pull hours ago
    would veto every later bounce, and an appear after a pull would hide it.
    Sitting size ≥ min_size is normal book, not this flag (0.2.5 = pulled).
    """
    start = require_utc(since)
    return any(event.kind == "pulled" and event.ts >= start for event in events)


class WallWatch:
    def __init__(self, symbol: str, *, min_size: Decimal) -> None:
        if min_size <= 0:
            raise ValueError("min_size must be > 0")
        self.symbol = symbol
        self.min_size = min_size
        self._walls: dict[tuple[WallSide, Decimal], _Tracked] = {}
        self.events: list[WallEvent] = []

    def on_book_and_trade(
        self,
        book: Book,
        trade: MarketEvent | None = None,
        *,
        ts: datetime,
    ) -> list[WallEvent]:
        when = require_utc(ts)
        if not book.ready:
            return []
        if trade is not None:
            self._on_trade(trade)
        out = self._on_book(book, when)
        self.events.extend(out)
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
        for side in ("bid", "ask"):
            for px, sz in book.levels(side).items():
                if sz >= self.min_size:
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
