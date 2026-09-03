"""0.2.4 — gap or dirty book → REST snapshot. Book becomes the snapshot.

The failed delta is discarded. Next diffs apply only after the new `u`.
Fetch is injected; we never invent depth.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from capitalizator.book.reconstruct import Book, BookDirty
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import ExchangeName, MarketEvent, require_utc


class BookResync:
    def __init__(
        self,
        book: Book,
        fetch_snapshot: Callable[[], BookSnapshot],
        *,
        symbol: str,
        exchange: ExchangeName = "bybit",
    ) -> None:
        self.book = book
        self._fetch_snapshot = fetch_snapshot
        self.symbol = symbol
        self.exchange = exchange
        self.events: list[MarketEvent] = []

    def on_gap(
        self,
        *,
        recv_ts: datetime,
        exchange_ts: datetime | None = None,
    ) -> MarketEvent:
        snap = self._fetch_snapshot()
        self.book.apply_snapshot(snap)
        event = MarketEvent(
            stream="resync",
            exchange=self.exchange,
            symbol=self.symbol,
            exchange_ts=require_utc(exchange_ts or snap.exchange_ts),
            recv_ts=require_utc(recv_ts),
            seq=snap.seq,
            payload={
                "update_id": snap.seq,
                "cross_seq": snap.cross_seq,
                "bid_levels": len(snap.bids),
                "ask_levels": len(snap.asks),
                # Levels ride along so a reader (the desk) can rebuild its book from
                # the tape instead of only learning that the book went dirty.
                "bids": [list(x) for x in snap.bids],
                "asks": [list(x) for x in snap.asks],
            },
        )
        self.events.append(event)
        return event

    def feed(
        self,
        kind: str,
        snap: BookSnapshot,
        *,
        recv_ts: datetime,
    ) -> list[MarketEvent]:
        try:
            if kind == "snapshot":
                self.book.apply_snapshot(snap)
            else:
                self.book.apply_diff(snap.bids, snap.asks, seq=snap.seq)
        except (BookDirty, SeqFault):
            # Discard the failed delta's clock. Resync time is the snapshot we fetched.
            return [self.on_gap(recv_ts=recv_ts)]
        return []
