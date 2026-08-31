"""0.3.1 — zones from bars with close_ts < t. No future bar, no ICT/FVG."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.types import require_utc
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Bar, Zone, ZoneMethod, ZoneSide


class ZoneEngine:
    """prior_day_hl + last confirmed swing. Methods not in the enum cannot exist."""

    def __init__(
        self,
        *,
        tick_size: Decimal,
        config: RegistryConfig | None = None,
    ) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        self.tick_size = tick_size
        self.config = config or load_registry()

    def build(self, symbol: str, t: datetime, bars: Sequence[Bar]) -> list[Zone]:
        when = require_utc(t)
        visible = [
            b
            for b in bars
            if b.symbol == symbol and b.close_ts < when
        ]
        visible.sort(key=lambda b: b.close_ts)
        out: list[Zone] = []
        out.extend(self._prior_day(symbol, when, visible))
        out.extend(self._swings(symbol, visible))
        out.sort(key=lambda z: (z.created_as_of, z.method, z.side, z.lo))
        return out

    def _band(self, level: Decimal, side: ZoneSide) -> tuple[Decimal, Decimal]:
        width = self.tick_size * self.config.epsilon_ticks
        if side == "support":
            return level, level + width
        return level - width, level

    def _prior_day(self, symbol: str, t: datetime, visible: list[Bar]) -> list[Zone]:
        prior_date = t.date() - timedelta(days=1)
        day_bars = [b for b in visible if b.close_ts.date() == prior_date]
        if not day_bars:
            return []
        high = max(b.high for b in day_bars)
        low = min(b.low for b in day_bars)
        created = datetime(t.year, t.month, t.day, tzinfo=UTC)
        if created >= t:
            return []
        return [
            self._zone(symbol, "1d", "support", *self._band(low, "support"), "prior_day_hl", created),
            self._zone(
                symbol, "1d", "resistance", *self._band(high, "resistance"), "prior_day_hl", created
            ),
        ]

    def _swings(self, symbol: str, visible: list[Bar]) -> list[Zone]:
        work = [b for b in visible if b.tf == self.config.working_tf]
        if len(work) < 3:
            return []
        out: list[Zone] = []
        last_sup: Zone | None = None
        last_res: Zone | None = None
        for i in range(1, len(work) - 1):
            prev, mid, nxt = work[i - 1], work[i], work[i + 1]
            created = nxt.close_ts
            if mid.high > prev.high and mid.high > nxt.high:
                last_res = self._zone(
                    symbol,
                    mid.tf,
                    "resistance",
                    *self._band(mid.high, "resistance"),
                    "swing",
                    created,
                )
            if mid.low < prev.low and mid.low < nxt.low:
                last_sup = self._zone(
                    symbol,
                    mid.tf,
                    "support",
                    *self._band(mid.low, "support"),
                    "swing",
                    created,
                )
        if last_sup is not None:
            out.append(last_sup)
        if last_res is not None:
            out.append(last_res)
        return out

    def _zone(
        self,
        symbol: str,
        tf: str,
        side: ZoneSide,
        lo: Decimal,
        hi: Decimal,
        method: ZoneMethod,
        created_as_of: datetime,
    ) -> Zone:
        return Zone.create(
            symbol=symbol,
            tf=tf,
            side=side,
            lo=lo,
            hi=hi,
            method=method,
            created_as_of=created_as_of,
        )
