"""Point-in-time types. Naive datetimes are forbidden."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StreamName = Literal[
    "trades",
    "book_diff",
    "bbo",
    "funding",
    "oi",
    "mark",
    "gap",
    "resync",
    "snapshot",
    "liquidation",
]
ExchangeName = Literal["bybit", "mexc"]


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise TypeError("naive datetime is forbidden; pass tz-aware UTC")
    return value.astimezone(UTC)


class UtcDateTime:
    """Marker helper: construct only tz-aware UTC datetimes."""

    @staticmethod
    def parse(value: datetime) -> datetime:
        return require_utc(value)


class PitInstant(BaseModel):
    """as_of = world at that moment; known_at = when we learned it."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    known_at: datetime

    @field_validator("as_of", "known_at")
    @classmethod
    def _utc_only(cls, value: datetime) -> datetime:
        return require_utc(value)


class MarketEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: StreamName
    exchange: ExchangeName
    symbol: str
    exchange_ts: datetime
    recv_ts: datetime
    seq: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("exchange_ts", "recv_ts")
    @classmethod
    def _utc_only(cls, value: datetime) -> datetime:
        return require_utc(value)


def known_by(known_at: datetime, as_of: datetime) -> bool:
    """True if a fact with this known_at is visible on a slice at as_of."""
    return require_utc(known_at) <= require_utc(as_of)
