"""Funding fields shared by the WS and REST ticker parsers.

tickers.{symbol} (WS) and GET /v5/market/tickers (REST) both carry, for linear
perpetuals: `fundingRate`, `nextFundingTime` (ms), `fundingIntervalHour` (whole
hours; Bybit switches a contract to hourly settlement when the rate pins its cap
and reverts without notice — 2025-10-30 announcement) and `turnover24h` (USDT).
Docs: https://bybit-exchange.github.io/docs/v5/websocket/public/ticker

Absent fields stay absent from the payload. There is no default of 8 hours here:
the desk keeps the last interval it saw, or the instruments-info value.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


def funding_payload(item: Mapping[str, Any]) -> dict[str, str]:
    out = {"funding": str(item["fundingRate"])}
    nxt = item.get("nextFundingTime")
    if nxt not in (None, ""):
        try:
            out["next_funding_ts"] = str(int(str(nxt)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"nextFundingTime not an integer: {nxt!r}") from exc
    hours = item.get("fundingIntervalHour")
    if hours not in (None, ""):
        try:
            ih = int(str(hours))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fundingIntervalHour not an integer: {hours!r}") from exc
        if ih <= 0:
            raise ValueError(f"fundingIntervalHour must be > 0: {hours!r}")
        out["interval_min"] = str(ih * 60)
    turnover = item.get("turnover24h")
    if turnover not in (None, ""):
        try:
            Decimal(str(turnover))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"turnover24h not a number: {turnover!r}") from exc
        out["turnover24h"] = str(turnover)
    return out
