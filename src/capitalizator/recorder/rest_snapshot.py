"""Parse Bybit linear orderbook REST snapshot. Fetch is injectable (no keys).

Bybit fields (GET /v5/market/orderbook):
- `u` — update id, consecutive on this book. We store it as BookSnapshot.seq
  and use it for apply/gap. Official: "u is always in sequence".
- `seq` — cross sequence. Monotonic but *not* consecutive. We store it as
  cross_seq and never gap-check it.
Docs: https://bybit-exchange.github.io/docs/v5/market/orderbook
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from capitalizator.types import ExchangeName, MarketEvent, require_utc


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    exchange_ts: datetime  # matching-engine time: Bybit `cts`, else `ts`
    seq: int  # Bybit `u`
    bids: tuple[tuple[str, str], ...]
    asks: tuple[tuple[str, str], ...]
    cross_seq: int | None = None  # Bybit `seq`
    system_ts: datetime | None = None  # Bybit `ts` when both exist


def book_times(
    data: dict[str, Any],
    frame: dict[str, Any] | None = None,
) -> tuple[datetime, datetime | None]:
    """exchange_ts = cts (matches publicTrade.T). Fallback ts. Official WS/REST.

    https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
    """
    frame = frame or {}
    cts = data.get("cts") if data.get("cts") is not None else frame.get("cts")
    ts = data.get("ts") if data.get("ts") is not None else frame.get("ts")
    if cts is None and ts is None:
        raise ValueError("book payload missing cts and ts")
    engine = datetime.fromtimestamp(int(cts if cts is not None else ts) / 1000, tz=UTC)
    system = None
    if ts is not None:
        system = datetime.fromtimestamp(int(ts) / 1000, tz=UTC)
    return require_utc(engine), require_utc(system) if system is not None else None


def _levels(rows: list[Any]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            raise ValueError("level must be [price, size]")
        px, sz = str(row[0]), str(row[1])
        price = Decimal(px)
        size = Decimal(sz)
        if price <= 0:
            raise ValueError(f"level price must be > 0, got {price}")
        if size < 0:
            raise ValueError(f"level size must be >= 0, got {size}")
        out.append((px, sz))
    return tuple(out)


def _require_update_id(data: dict[str, Any]) -> int:
    if data.get("u") is None:
        raise ValueError("book payload missing u (Bybit update id)")
    return int(data["u"])


class RestSnapshot:
    URL = "https://api.bybit.com/v5/market/orderbook"

    def parse(self, payload: dict[str, Any]) -> BookSnapshot:
        if payload.get("retCode") not in (0, None):
            raise ValueError(f"bybit retCode {payload.get('retCode')}")
        result = payload.get("result") or payload
        if not isinstance(result, dict):
            raise ValueError("snapshot result must be an object")
        if "s" not in result:
            raise ValueError("snapshot missing s")
        symbol = str(result["s"])
        exchange_ts, system_ts = book_times(result)
        bids = _levels(list(result.get("b") or []))
        asks = _levels(list(result.get("a") or []))
        if not bids or not asks:
            raise ValueError("snapshot depth is zero")
        cross = result.get("seq")
        return BookSnapshot(
            symbol=symbol,
            exchange_ts=exchange_ts,
            seq=_require_update_id(result),
            bids=bids,
            asks=asks,
            cross_seq=int(cross) if cross is not None else None,
            system_ts=system_ts,
        )

    def fetch(self, symbol: str, *, opener: Any | None = None) -> BookSnapshot:
        query = urlencode({"category": "linear", "symbol": symbol, "limit": 200})
        url = f"{self.URL}?{query}"
        raw = (opener or _default_get)(url)
        if isinstance(raw, bytes):
            payload = json.loads(raw.decode())
        elif isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = raw
        return self.parse(payload)

    def to_event(
        self,
        snap: BookSnapshot,
        *,
        recv_ts: datetime,
        exchange: ExchangeName = "bybit",
    ) -> MarketEvent:
        return MarketEvent(
            stream="snapshot",
            exchange=exchange,
            symbol=snap.symbol,
            exchange_ts=snap.exchange_ts,
            recv_ts=require_utc(recv_ts),
            seq=snap.seq,
            payload={
                "bids": list(snap.bids),
                "asks": list(snap.asks),
                "cross_seq": snap.cross_seq,
                "system_ts": snap.system_ts.isoformat() if snap.system_ts else None,
            },
        )


def _default_get(url: str) -> bytes:
    with urlopen(url, timeout=10) as resp:  # noqa: S310 — public market data only
        return resp.read()
