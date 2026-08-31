"""Normalize public Bybit trade payloads into MarketEvent."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from capitalizator.types import ExchangeName, MarketEvent, require_utc


def _ms_to_utc(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


def _require_fields(raw: dict[str, Any], names: tuple[str, ...]) -> None:
    missing = [name for name in names if name not in raw]
    if missing:
        raise ValueError(f"trade payload missing {missing}")


def normalize_bybit_public_trade(
    raw: dict[str, Any],
    *,
    recv_ts: datetime,
    seq: int | None = None,
    exchange: ExchangeName = "bybit",
) -> MarketEvent:
    """Map one Bybit publicTrade item to MarketEvent.

    `seq` on the wire is a *cross* sequence. Official note: several messages
    may carry the same seq (up to 1024 trades per message).
    https://bybit-exchange.github.io/docs/v5/websocket/public/trade
    We store that number. We do not invent 1,2,3 and we do not gap-check it.
    """
    _require_fields(raw, ("T", "s", "p", "v"))
    side = str(raw.get("S") or raw.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError(f"unknown trade side: {side!r}")
    px = Decimal(str(raw["p"]))
    qty = Decimal(str(raw["v"]))
    if px <= 0 or qty <= 0:
        raise ValueError(f"trade px/qty must be > 0, got {px} / {qty}")
    if seq is None and raw.get("seq") is not None:
        seq = int(raw["seq"])
    return MarketEvent(
        stream="trades",
        exchange=exchange,
        symbol=str(raw["s"]),
        exchange_ts=_ms_to_utc(raw["T"]),
        recv_ts=require_utc(recv_ts),
        seq=seq,
        payload={
            "px": str(px),
            "qty": str(qty),
            "side": side,
            "trade_id": raw.get("i"),
            "cross_seq": seq,
        },
    )


class TradesNormalizer:
    def normalize(
        self,
        raw: dict[str, Any],
        *,
        recv_ts: datetime,
        seq: int | None = None,
        exchange: ExchangeName = "bybit",
    ) -> MarketEvent:
        return normalize_bybit_public_trade(raw, recv_ts=recv_ts, seq=seq, exchange=exchange)

    def normalize_frame(
        self,
        frame: dict[str, Any],
        *,
        recv_ts: datetime,
        exchange: ExchangeName = "bybit",
    ) -> list[MarketEvent]:
        """Unwrap a Bybit WS frame `{topic, data: [...]}` or a single trade."""
        if "data" in frame and isinstance(frame["data"], list):
            items = frame["data"]
        elif "T" in frame and "s" in frame:
            items = [frame]
        else:
            raise ValueError("not a Bybit publicTrade frame")
        events: list[MarketEvent] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("trade item must be an object")
            events.append(self.normalize(item, recv_ts=recv_ts, exchange=exchange))
        return events
