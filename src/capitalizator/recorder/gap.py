"""Holes in a *consecutive* id become explicit gap events.

Use this on Bybit orderbook `u`, not on publicTrade `seq`.
Official: several trade messages may share one seq
(https://bybit-exchange.github.io/docs/v5/websocket/public/trade).
Never swallow a skip or rewind on a consecutive stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from capitalizator.types import ExchangeName, MarketEvent, require_utc


class SeqFault(ValueError):
    """Duplicate or backwards seq. Not a hole — a broken stream."""


@dataclass(frozen=True)
class Gap:
    seq_from: int
    seq_to: int


class GapDetector:
    def on_seq(self, prev: int | None, cur: int) -> Gap | None:
        if prev is None:
            return None
        if cur == prev + 1:
            return None
        if cur > prev + 1:
            # 5 -> 8 means missing 6 and 7 inclusive.
            return Gap(seq_from=prev + 1, seq_to=cur - 1)
        raise SeqFault(f"seq not monotonic: {prev} -> {cur}")

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
