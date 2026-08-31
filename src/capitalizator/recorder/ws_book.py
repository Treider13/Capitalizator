"""Drive already-decoded orderbook frames. No keys. Socket is injected."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from capitalizator.book.reconstruct import Book
from capitalizator.recorder.book_diff import BookDiffNormalizer
from capitalizator.types import ExchangeName, MarketEvent, require_utc


class BybitBookWs:
    """Snapshot + deltas → MarketEvents. Does not open a live socket."""

    def __init__(self, *, book: Book | None = None) -> None:
        self.normalizer = BookDiffNormalizer()
        self.book = book or Book()

    def ingest_frames(
        self,
        frames: Iterable[dict[str, Any]],
        *,
        recv_ts: datetime | None = None,
        exchange: ExchangeName = "bybit",
    ) -> list[MarketEvent]:
        now = recv_ts or datetime.now(tz=UTC)
        require_utc(now)
        out: list[MarketEvent] = []
        for frame in frames:
            kind, snap = self.normalizer.parse_frame(frame)
            if kind == "snapshot":
                self.book.apply_snapshot(snap)
            else:
                self.book.apply_diff(snap.bids, snap.asks, seq=snap.seq)
            out.append(self.normalizer.to_event(kind, snap, recv_ts=now, exchange=exchange))
            bbo = self._bbo_event(snap.symbol, snap.exchange_ts, now, exchange)
            if bbo is not None:
                out.append(bbo)
        return out

    def _bbo_event(
        self,
        symbol: str,
        exchange_ts: datetime,
        recv_ts: datetime,
        exchange: ExchangeName,
    ) -> MarketEvent | None:
        bid, ask = self.book.best()
        if bid is None or ask is None:
            return None
        return MarketEvent(
            stream="bbo",
            exchange=exchange,
            symbol=symbol,
            exchange_ts=exchange_ts,
            recv_ts=recv_ts,
            seq=self.book.seq,
            payload={
                "bid": str(bid),
                "ask": str(ask),
                "bid_sz": str(self.book.level("bid", str(bid))),
                "ask_sz": str(self.book.level("ask", str(ask))),
            },
        )
