"""15m bars from trade prints. Only closed buckets. No invented OHLC."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar

TF_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def bucket_open(ts: datetime, *, minutes: int) -> datetime:
    when = ts.astimezone(UTC)
    total = when.hour * 60 + when.minute
    floored = (total // minutes) * minutes
    return when.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def closed_bars_from_trades(
    trades: Sequence[MarketEvent],
    *,
    symbol: str,
    tf: str,
    now: datetime,
    already: set[datetime],
) -> list[Bar]:
    minutes = TF_MINUTES.get(tf)
    if minutes is None:
        raise ValueError(f"unsupported working tf: {tf!r}")
    buckets: dict[datetime, list[MarketEvent]] = {}
    for trade in trades:
        if trade.symbol != symbol or trade.stream != "trades":
            continue
        try:
            px = Decimal(str(trade.payload["px"]))
            qty = Decimal(str(trade.payload.get("qty") or "0"))
        except (KeyError, ArithmeticError):
            continue
        if px <= 0 or qty < 0:
            continue
        start = bucket_open(trade.exchange_ts, minutes=minutes)
        buckets.setdefault(start, []).append(trade)
    out: list[Bar] = []
    for start, rows in sorted(buckets.items()):
        close_ts = start + timedelta(minutes=minutes)
        if close_ts > now or start in already:
            continue
        px = [Decimal(str(r.payload["px"])) for r in rows]
        vol = sum((Decimal(str(r.payload.get("qty") or "0")) for r in rows), Decimal("0"))
        out.append(
            Bar(
                symbol=symbol,
                tf=tf,
                open_ts=start,
                close_ts=close_ts,
                open=px[0],
                high=max(px),
                low=min(px),
                close=px[-1],
                volume=vol,
            )
        )
    return out
