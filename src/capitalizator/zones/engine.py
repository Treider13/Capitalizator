"""0.3.1 — zones from bars with close_ts < t. No future bar, no ICT/FVG."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.patterns.bar_quality import atr
from capitalizator.types import require_utc
from capitalizator.zones.config import RegistryConfig, load_registry
from capitalizator.zones.model import Bar, Zone, ZoneMethod, ZoneSide
from capitalizator.zones.pair import invalidated
from capitalizator.zones.session_vp import (
    SESSION_VP_WINDOWS,
    last_closed_bounds,
    method_for,
    session_profile,
)

# Levels whose price comes from a day/session/card, but CAV votes working_tf.
MAP_VOTE_METHODS = frozenset(
    {
        "prior_day_hl",
        "prior_session_hl",
        "vp_hyp",
        "session_vp_asia",
        "session_vp_europe",
        "session_vp_overlap",
        "session_vp_us",
    }
)
# Half-width of an S/R band as a fraction of that TF's ATR (noise envelope).
# Tick epsilon stays the floor when ATR is unmeasured — never an invented move.
ZONE_ATR_K = Decimal("0.25")


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
        out.extend(self._session_vp(symbol, when, visible))
        out = [z for z in out if not invalidated(z, visible, t=when)]
        out.sort(key=lambda z: (z.created_as_of, z.method, z.side, z.lo))
        return out

    def _width(self, bars: Sequence[Bar], tf: str, created_as_of: datetime) -> Decimal:
        """PIT envelope at created_as_of: max(tick epsilon, k × ATR of this TF)."""
        floor = self.tick_size * self.config.epsilon_ticks
        series = [b for b in bars if b.tf == tf and b.close_ts < created_as_of]
        if len({b.symbol for b in series}) != 1:
            return floor
        try:
            value = atr(series)
        except ValueError:
            value = None
        if value is None or value <= 0:
            return floor
        return max(floor, value * ZONE_ATR_K)

    def _band(
        self,
        level: Decimal,
        side: ZoneSide,
        *,
        bars: Sequence[Bar],
        tf: str,
        created_as_of: datetime,
    ) -> tuple[Decimal, Decimal]:
        width = self._width(bars, tf, created_as_of)
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
                symbol,
                vote_tf,
                "support",
                *self._band(low, "support", bars=visible, tf=vote_tf, created_as_of=created),
                "prior_day_hl",
                created,
            ),
            self._zone(
                symbol,
                vote_tf,
                "resistance",
                *self._band(high, "resistance", bars=visible, tf=vote_tf, created_as_of=created),
                "prior_day_hl",
                created,
            ),
        ]

    def _swings(self, symbol: str, visible: list[Bar]) -> list[Zone]:
        out: list[Zone] = []
        for tf in self.config.structure_tfs:
            out.extend(self._swings_tf(symbol, [b for b in visible if b.tf == tf]))
        return out

    def _swings_tf(self, symbol: str, work: list[Bar]) -> list[Zone]:
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
                    *self._band(
                        mid.high, "resistance", bars=work, tf=mid.tf, created_as_of=created
                    ),
                    "swing",
                    created,
                )
            if mid.low < prev.low and mid.low < nxt.low:
                last_sup = self._zone(
                    symbol,
                    mid.tf,
                    "support",
                    *self._band(
                        mid.low, "support", bars=work, tf=mid.tf, created_as_of=created
                    ),
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
                *self._band(low, "support", bars=visible, tf=vote_tf, created_as_of=created),
                "prior_session_hl",
                created,
            ),
            self._zone(
                symbol,
                vote_tf,
                "resistance",
                *self._band(high, "resistance", bars=visible, tf=vote_tf, created_as_of=created),
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
                symbol,
                last.tf,
                "support",
                *self._band(level, "support", bars=work, tf=last.tf, created_as_of=created),
                "round",
                created,
            ),
            self._zone(
                symbol,
                last.tf,
                "resistance",
                *self._band(level, "resistance", bars=work, tf=last.tf, created_as_of=created),
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
        width = self._width(work, window[-1].tf, created)
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
        vote_tf = self.config.working_tf
        width = self._width(visible, vote_tf, created)
        return [
            self._zone(symbol, vote_tf, "support", poc, poc + width, "vp_hyp", created),
            self._zone(symbol, vote_tf, "resistance", poc - width, poc, "vp_hyp", created),
        ]

    def _session_vp(self, symbol: str, t: datetime, visible: list[Bar]) -> list[Zone]:
        """Yesterday's Asia/London-overlap/US value-area edges. Empty session → none."""
        from capitalizator.risk.sessions import SessionPolicy

        policy = SessionPolicy.load()
        vote_tf = self.config.working_tf
        work = [b for b in visible if b.tf == vote_tf]
        out: list[Zone] = []
        for name in SESSION_VP_WINDOWS:
            bounds = last_closed_bounds(policy.window_named(name), t)
            if bounds is None:
                continue
            start, end = bounds
            if end >= t:
                continue
            session = [b for b in work if start <= b.close_ts < end]
            profile = session_profile(session, tick=self.tick_size)
            if profile is None:
                continue
            _poc, vah, val = profile
            method = method_for(name)
            out.append(
                self._zone(
                    symbol,
                    vote_tf,
                    "support",
                    *self._band(val, "support", bars=work, tf=vote_tf, created_as_of=end),
                    method,
                    end,
                )
            )
            out.append(
                self._zone(
                    symbol,
                    vote_tf,
                    "resistance",
                    *self._band(vah, "resistance", bars=work, tf=vote_tf, created_as_of=end),
                    method,
                    end,
                )
            )
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
