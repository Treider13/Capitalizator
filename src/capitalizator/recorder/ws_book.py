"""Drive already-decoded orderbook frames. No keys. Socket is injected."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from capitalizator.book.reconstruct import Book
from capitalizator.book.resync import BookResync
from capitalizator.recorder.book_diff import BookDiffNormalizer
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import ExchangeName, MarketEvent, require_utc


class BybitBookWs:
    """Snapshot + deltas → MarketEvents. Does not open a live socket.

    If `fetch_snapshot` is set, a gap/`BookDirty` discards the failed delta
    and replaces the book with that snapshot (0.2.4). Without a fetch,
    the exception still surfaces — we do not invent depth.
    """

    def __init__(
        self,
        *,
        book: Book | None = None,
        fetch_snapshot: Callable[[], BookSnapshot] | None = None,
        symbol: str = "BTCUSDT",
        exchange: ExchangeName = "bybit",
    ) -> None:
        self.normalizer = BookDiffNormalizer()
        self.book = book or Book()
        self.resync = (
            BookResync(self.book, fetch_snapshot, symbol=symbol, exchange=exchange)
            if fetch_snapshot is not None
            else None
        )

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
            if self.resync is not None:
                recovered = self.resync.feed(kind, snap, recv_ts=now)
                if recovered:
                    out.extend(recovered)
                    bbo = self._bbo_event(snap.symbol, snap.exchange_ts, now, exchange)
                    if bbo is not None:
                        out.append(bbo)
                    continue
            elif kind == "snapshot":
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
