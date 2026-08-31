"""0.3.7 — BTC regime as a label on the touch. No veto(), no trade.

trend / box from closed HTF (ZoneMap.htf_bias).
news only if a calendar row is already known_at ≤ t — we do not invent news from range.
unknown HTF and no news → None, not a guessed 'trend'.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from capitalizator.types import require_utc
from capitalizator.zones.map import HtfBias, ZoneMap
from capitalizator.zones.model import Bar

BtcLabel = Literal["trend", "box", "news"]


class BtcRegime:
    def __init__(self, mapper: ZoneMap | None = None) -> None:
        self.mapper = mapper or ZoneMap()

    def classify(
        self,
        t: datetime,
        *,
        symbol: str = "BTCUSDT",
        bars: Sequence[Bar] = (),
        htf_bias: HtfBias | None = None,
        news_known_at: datetime | None = None,
    ) -> BtcLabel | None:
        when = require_utc(t)
        if news_known_at is not None and require_utc(news_known_at) <= when:
            return "news"
        bias = htf_bias if htf_bias is not None else self.mapper.htf_bias(symbol, when, bars)
        if bias in {"long", "short"}:
            return "trend"
        if bias == "box":
            return "box"
        return None
