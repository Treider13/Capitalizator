"""Normalize Bybit orderbook WS frames to snapshot/diff payloads.

Topic in PHASE-BUILD: orderbook.200.BTCUSDT (linear).
Apply/gap id is data.u, not data.seq.
Docs: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from capitalizator.recorder.rest_snapshot import (
    BookSnapshot,
    _levels,
    _require_update_id,
    book_times,
)
from capitalizator.types import ExchangeName, MarketEvent, require_utc


class BookDiffNormalizer:
    def parse_frame(self, frame: dict[str, Any]) -> tuple[str, BookSnapshot]:
        data = frame.get("data") or frame
        if not isinstance(data, dict):
            raise ValueError("book frame data must be an object")
        raw_kind = frame.get("type")
        if raw_kind is None and isinstance(data, dict):
            raw_kind = data.get("type")
        if raw_kind is None:
            raise ValueError("book frame missing type")
        kind: Literal["snapshot", "delta"] = raw_kind
        if kind not in {"snapshot", "delta"}:
            raise ValueError(f"unknown book type {kind!r}")
        if "s" not in data:
            raise ValueError("book frame missing s")
        exchange_ts, system_ts = book_times(data, frame)
        cross = data.get("seq")
        snap = BookSnapshot(
            symbol=str(data["s"]),
            exchange_ts=exchange_ts,
            seq=_require_update_id(data),
            bids=_levels(list(data.get("b") or [])),
            asks=_levels(list(data.get("a") or [])),
            cross_seq=int(cross) if cross is not None else None,
            system_ts=system_ts,
        )
        return kind, snap

    def to_event(
        self,
        kind: str,
        snap: BookSnapshot,
        *,
        recv_ts: datetime,
        exchange: ExchangeName = "bybit",
    ) -> MarketEvent:
        stream: Literal["snapshot", "book_diff"] = "snapshot" if kind == "snapshot" else "book_diff"
        return MarketEvent(
            stream=stream,
            exchange=exchange,
            symbol=snap.symbol,
            exchange_ts=snap.exchange_ts,
            recv_ts=require_utc(recv_ts),
            seq=snap.seq,
            payload={
                "bids": list(snap.bids),
                "asks": list(snap.asks),
                "kind": kind,
                "cross_seq": snap.cross_seq,
                "system_ts": snap.system_ts.isoformat() if snap.system_ts else None,
            },
        )
