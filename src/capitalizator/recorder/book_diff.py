"""Normalize Bybit orderbook WS frames to snapshot/diff payloads.

Topic in PHASE-BUILD: orderbook.200.BTCUSDT (linear).
Apply/gap id is data.u, not data.seq.
Docs: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from capitalizator.recorder.rest_snapshot import BookSnapshot, _levels, _require_update_id
from capitalizator.types import ExchangeName, MarketEvent, require_utc


def _ms_to_utc(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


class BookDiffNormalizer:
    def parse_frame(self, frame: dict[str, Any]) -> tuple[str, BookSnapshot]:
        data = frame.get("data") or frame
        if not isinstance(data, dict):
            raise ValueError("book frame data must be an object")
        kind: Literal["snapshot", "delta"] = frame.get("type") or data.get("type") or "delta"
        if kind not in {"snapshot", "delta"}:
            raise ValueError(f"unknown book type {kind!r}")
        ts = frame.get("ts") or data.get("ts") or frame.get("cts") or data.get("cts")
        if ts is None:
            raise ValueError("book frame missing ts")
        if "s" not in data:
            raise ValueError("book frame missing s")
        cross = data.get("seq")
        snap = BookSnapshot(
            symbol=str(data["s"]),
            exchange_ts=require_utc(_ms_to_utc(ts)),
            seq=_require_update_id(data),
            bids=_levels(list(data.get("b") or [])),
            asks=_levels(list(data.get("a") or [])),
            cross_seq=int(cross) if cross is not None else None,
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
        stream = "snapshot" if kind == "snapshot" else "book_diff"
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
            },
        )
