"""Normalize public Bybit (and later MEXC) trade payloads into MarketEvent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from capitalizator.types import ExchangeName, MarketEvent, require_utc


def _ms_to_utc(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


def normalize_bybit_public_trade(
    raw: dict[str, Any],
    *,
    recv_ts: datetime,
    seq: int | None = None,
    exchange: ExchangeName = "bybit",
) -> MarketEvent:
    """Map one Bybit publicTrade item to MarketEvent."""
    if "T" not in raw or "s" not in raw:
        raise ValueError("not a Bybit public trade payload")
    side = str(raw.get("S") or raw.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError(f"unknown trade side: {side!r}")
    return MarketEvent(
        stream="trades",
        exchange=exchange,
        symbol=str(raw["s"]),
        exchange_ts=_ms_to_utc(raw["T"]),
        recv_ts=require_utc(recv_ts),
        seq=seq,
        payload={
            "px": str(raw["p"]),
            "qty": str(raw["v"]),
            "side": side,
            "trade_id": raw.get("i"),
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
