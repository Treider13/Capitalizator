"""Parse Bybit linear ticker REST. Fetch is injectable. No keys.

GET /v5/market/tickers?category=linear&symbol=BTCUSDT
Docs: https://bybit-exchange.github.io/docs/v5/market/tickers

Plan §6.1: funding / OI / mark are REST+WS. WS is tickers.{symbol}.
REST is the same three fields from this public endpoint.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from capitalizator.recorder.ticker_fields import funding_payload
from capitalizator.types import MarketEvent, require_utc


class RestTicker:
    URL = "https://api.bybit.com/v5/market/tickers"

    def parse(self, payload: dict[str, Any], *, recv_ts: datetime) -> list[MarketEvent]:
        if payload.get("retCode") not in (0, None):
            raise ValueError(f"bybit retCode {payload.get('retCode')}")
        result = payload.get("result") or payload
        if not isinstance(result, dict):
            raise ValueError("ticker result must be an object")
        rows = result.get("list")
        if not isinstance(rows, list):
            raise ValueError("ticker list must be an array")
        when = require_utc(recv_ts)
        out: list[MarketEvent] = []
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError("ticker row must be an object")
            symbol = str(item.get("symbol") or "")
            if not symbol:
                raise ValueError("ticker row missing symbol")
            ts_raw = item.get("ts") or item.get("T")
            exchange_ts = (
                datetime.fromtimestamp(int(ts_raw) / 1000, tz=UTC)
                if ts_raw is not None
                else when
            )
            if item.get("fundingRate") is not None:
                out.append(
                    MarketEvent(
                        stream="funding",
                        exchange="bybit",
                        symbol=symbol,
                        exchange_ts=exchange_ts,
                        recv_ts=when,
                        payload=funding_payload(item),
                    )
                )
            if item.get("openInterest") is not None or item.get("openInterestValue") is not None:
                oi = item.get("openInterest", item.get("openInterestValue"))
                out.append(
                    MarketEvent(
                        stream="oi",
                        exchange="bybit",
                        symbol=symbol,
                        exchange_ts=exchange_ts,
                        recv_ts=when,
                        payload={"oi": str(oi)},
                    )
                )
            mark_px = item.get("markPrice") or item.get("mark_price")
            if mark_px is not None:
                out.append(
                    MarketEvent(
                        stream="mark",
                        exchange="bybit",
                        symbol=symbol,
                        exchange_ts=exchange_ts,
                        recv_ts=when,
                        payload={"mark": str(mark_px)},
                    )
                )
        return out

    def fetch(
        self,
        symbol: str,
        *,
        recv_ts: datetime,
        opener: Any | None = None,
    ) -> list[MarketEvent]:
        query = urlencode({"category": "linear", "symbol": symbol})
        url = f"{self.URL}?{query}"
        raw = (opener or _default_get)(url)
        if isinstance(raw, bytes):
            payload = json.loads(raw.decode())
        elif isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = raw
        if not isinstance(payload, dict):
            raise ValueError("ticker payload must be an object")
        return self.parse(payload, recv_ts=recv_ts)


def _default_get(url: str) -> bytes:
    with urlopen(url, timeout=10) as resp:  # noqa: S310 — public market data only
        return bytes(resp.read())
