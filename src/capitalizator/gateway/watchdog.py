"""Gateway-side dead-man (Н-4/Н-5).

The old DeadMan beat and ticked itself inside one loop iteration and could never
fire. Bybit's own DCP is institutional-only (docs: "DCP feature is only available
for Ins clients"), so protection is: (1) the stop-loss lives on the exchange from
the fill, (2) this watchdog cancels *entry* orders when the desk heartbeat, the
private WebSocket or the exchange clock goes silent. It never touches stops.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from capitalizator.types import require_utc


@dataclass
class Watchdog:
    dead_man_s: int
    cancel_entries: Callable[[str], None]  # reason → cancel all entry orders
    max_clock_skew_ms: int = 2000
    _last: dict[str, datetime] = field(default_factory=dict)
    fired: list[tuple[datetime, str]] = field(default_factory=list)
    armed: bool = False
    clock_skew_ms: int | None = None

    def __post_init__(self) -> None:
        if self.dead_man_s <= 0:
            raise ValueError("dead_man_s must be > 0")

    def beat(self, source: str, now: datetime) -> None:
        """desk | ws_private | ws_public. Arms on the first beat of each source."""
        self._last[source] = require_utc(now)
        self.armed = True

    def note_clock(self, *, local: datetime, exchange: datetime) -> None:
        delta = require_utc(local) - require_utc(exchange)
        self.clock_skew_ms = int(delta.total_seconds() * 1000)

    def stale(self, now: datetime) -> list[str]:
        when = require_utc(now)
        out = [
            src
            for src, ts in self._last.items()
            if (when - ts).total_seconds() > self.dead_man_s
        ]
        if self.clock_skew_ms is not None and abs(self.clock_skew_ms) > self.max_clock_skew_ms:
            out.append("clock")
        return sorted(out)

    def check(self, now: datetime) -> list[str]:
        """Cancel entries once per stale episode; stops stay on the venue."""
        if not self.armed:
            return []
        stale = self.stale(now)
        if not stale:
            return []
        reason = "dead_man:" + ",".join(stale)
        if self.fired and self.fired[-1][1] == reason:
            return stale
        self.cancel_entries(reason)
        self.fired.append((require_utc(now), reason))
        return stale
