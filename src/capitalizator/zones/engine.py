"""0.3.1 — zones from bars with close_ts < t. No future bar, no ICT/FVG."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.types import require_utc
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Bar, Zone, ZoneMethod, ZoneSide


class ZoneEngine:
    """prior_day_hl + last confirmed swing. Methods not in the enum cannot exist.

    Map levels (prior_day / session / card POC) use working_tf. CAV compares bar.tf
    to zone.tf and the desk only votes on the working close — a 1d tag made NOISE.
    """

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

    def build(
        self,
        symbol: str,
        t: datetime,
        bars: Sequence[Bar],
        *,
        poc: Decimal | None = None,
    ) -> list[Zone]:
        when = require_utc(t)
        visible = [
            b
            for b in bars
            if b.symbol == symbol and b.close_ts < when
        ]
        visible.sort(key=lambda b: b.close_ts)
        out: list[Zone] = []
        out.extend(self._prior_day(symbol, when, visible))
        out.extend(self._prior_session(symbol, when, visible))
        out.extend(self._swings(symbol, visible))
        out.extend(self._rounds(symbol, when, visible))
        out.extend(self._cluster(symbol, visible))
        out.extend(self._poc_from_card(symbol, when, visible, poc))
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
        vote_tf = self.config.working_tf
        return [
            self._zone(
                symbol, vote_tf, "support", *self._band(low, "support"), "prior_day_hl", created
            ),
            self._zone(
                symbol,
                vote_tf,
                "resistance",
                *self._band(high, "resistance"),
                "prior_day_hl",
                created,
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

    def _prior_session(self, symbol: str, t: datetime, visible: list[Bar]) -> list[Zone]:
        """Previous Moscow desk window 13:30–16:30 UTC. No future bars."""
        from datetime import time
        from zoneinfo import ZoneInfo

        msk = ZoneInfo("Europe/Moscow")
        local = t.astimezone(msk)
        start = datetime.combine(local.date(), time(16, 30), tzinfo=msk)
        if local.timetz().replace(tzinfo=None) < time(16, 30):
            start = start - timedelta(days=1)
        prev_start = start - timedelta(days=1)
        prev_end = prev_start + timedelta(hours=3)
        session = [
            b
            for b in visible
            if prev_start <= b.close_ts.astimezone(msk) < prev_end
        ]
        if not session:
            return []
        high = max(b.high for b in session)
        low = min(b.low for b in session)
        created = prev_end.astimezone(UTC)
        if created >= t:
            return []
        vote_tf = self.config.working_tf
        return [
            self._zone(
                symbol,
                vote_tf,
                "support",
                *self._band(low, "support"),
                "prior_session_hl",
                created,
            ),
            self._zone(
                symbol,
                vote_tf,
                "resistance",
                *self._band(high, "resistance"),
                "prior_session_hl",
                created,
            ),
        ]

    def _rounds(self, symbol: str, t: datetime, visible: list[Bar]) -> list[Zone]:
        work = [b for b in visible if b.tf == self.config.working_tf]
        if not work:
            return []
        last = work[-1]
        raw = last.close
        step = Decimal("1") if raw >= 100 else Decimal("0.1")
        level = (raw / step).to_integral_value() * step
        created = last.close_ts
        if created >= t:
            return []
        return [
            self._zone(
                symbol, last.tf, "support", *self._band(level, "support"), "round", created
            ),
            self._zone(
                symbol,
                last.tf,
                "resistance",
                *self._band(level, "resistance"),
                "round",
                created,
            ),
        ]

    def _cluster(self, symbol: str, visible: list[Bar]) -> list[Zone]:
        work = [b for b in visible if b.tf == self.config.working_tf]
        if len(work) < 5:
            return []
        window = work[-8:]
        lows = sorted(b.low for b in window)
        highs = sorted(b.high for b in window)
        lo = lows[len(lows) // 2]
        hi = highs[len(highs) // 2]
        created = window[-1].close_ts
        width = self.tick_size * self.config.epsilon_ticks
        if hi - lo > width * 20:
            return []
        return [
            self._zone(
                symbol,
                window[-1].tf,
                "support",
                lo,
                lo + width,
                "cluster_edge",
                created,
            ),
            self._zone(
                symbol,
                window[-1].tf,
                "resistance",
                hi - width,
                hi,
                "cluster_edge",
                created,
            ),
        ]

    def _poc_from_card(
        self,
        symbol: str,
        t: datetime,
        visible: list[Bar],
        poc: Decimal | None,
    ) -> list[Zone]:
        """POC comes from the B card volume snapshot. No VWAP stand-in."""
        if poc is None or poc <= 0 or not visible:
            return []
        created = visible[-1].close_ts
        if created >= t:
            return []
        width = self.tick_size * self.config.epsilon_ticks
        vote_tf = self.config.working_tf
        return [
            self._zone(symbol, vote_tf, "support", poc, poc + width, "vp_hyp", created),
            self._zone(symbol, vote_tf, "resistance", poc - width, poc, "vp_hyp", created),
        ]

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
