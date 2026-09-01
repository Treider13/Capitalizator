"""Zone and bar types. No ICT/FVG methods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from capitalizator.types import require_utc
from capitalizator.zones.ids import make_zone_id

ZoneSide = Literal["support", "resistance"]
ZoneMethod = Literal[
    "prior_day_hl",
    "swing",
    "cluster_edge",
    "round",
    "prior_session_hl",
    "vp_hyp",
]


@dataclass(frozen=True)
class Bar:
    symbol: str
    tf: str
    open_ts: datetime
    close_ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None

    def __post_init__(self) -> None:
        require_utc(self.open_ts)
        require_utc(self.close_ts)
        if self.close_ts < self.open_ts:
            raise ValueError("bar close_ts must be >= open_ts")
        if self.high < self.low:
            raise ValueError("bar high must be >= low")
        if self.volume is not None and self.volume < 0:
            raise ValueError("bar volume must be >= 0")


@dataclass(frozen=True)
class Zone:
    zone_id: str
    symbol: str
    tf: str
    side: ZoneSide
    lo: Decimal
    hi: Decimal
    method: ZoneMethod
    created_as_of: datetime

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        tf: str,
        side: ZoneSide,
        lo: Decimal,
        hi: Decimal,
        method: ZoneMethod,
        created_as_of: datetime,
    ) -> Zone:
        if lo > hi:
            raise ValueError("zone lo must be <= hi")
        if lo <= 0:
            raise ValueError("zone price must be > 0")
        created = require_utc(created_as_of)
        zid = make_zone_id(
            symbol=symbol,
            tf=tf,
            side=side,
            lo=lo,
            hi=hi,
            method=method,
            created_as_of=created,
        )
        return cls(
            zone_id=zid,
            symbol=symbol,
            tf=tf,
            side=side,
            lo=lo,
            hi=hi,
            method=method,
            created_as_of=created,
        )
