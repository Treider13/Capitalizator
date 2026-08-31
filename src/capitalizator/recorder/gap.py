"""Seq holes become explicit gap events. Never swallow a skip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from capitalizator.types import ExchangeName, MarketEvent, require_utc


@dataclass(frozen=True)
class Gap:
    seq_from: int
    seq_to: int


class GapDetector:
    def on_seq(self, prev: int | None, cur: int) -> Gap | None:
        if prev is None:
            return None
        if cur <= prev:
            return None
        if cur == prev + 1:
            return None
        # 5 -> 8 means missing 6 and 7 inclusive.
        return Gap(seq_from=prev + 1, seq_to=cur - 1)

    def event(
        self,
        gap: Gap,
        *,
        symbol: str,
        stream: str,
        exchange: ExchangeName,
        exchange_ts: datetime,
        recv_ts: datetime,
    ) -> MarketEvent:
        return MarketEvent(
            stream="gap",
            exchange=exchange,
            symbol=symbol,
            exchange_ts=require_utc(exchange_ts),
            recv_ts=require_utc(recv_ts),
            seq=None,
            payload={
                "missing_stream": stream,
                "seq_from": gap.seq_from,
                "seq_to": gap.seq_to,
            },
        )
