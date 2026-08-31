"""0.3.2 — HTF bias from closed bars only. Not an entry."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from capitalizator.types import require_utc
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Bar

HtfBias = Literal["long", "short", "box", "unknown"]


class ZoneMap:
    def __init__(self, config: RegistryConfig | None = None) -> None:
        self.config = config or load_registry()

    def htf_bias(self, symbol: str, t: datetime, bars: Sequence[Bar]) -> HtfBias:
        when = require_utc(t)
        visible = [
            b
            for b in bars
            if b.symbol == symbol and b.tf == self.config.htf and b.close_ts < when
        ]
        visible.sort(key=lambda b: b.close_ts)
        if len(visible) < 3:
            return "unknown"
        last = visible[-1]
        window = visible[-3:-1]
        ceiling = max(b.high for b in window)
        floor = min(b.low for b in window)
        if last.close > ceiling:
            return "long"
        if last.close < floor:
            return "short"
        return "box"
