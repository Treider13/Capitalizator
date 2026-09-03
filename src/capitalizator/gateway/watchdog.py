"""Gateway-side dead-man (Н-4/Н-5).

Bybit's own DCP is institutional-only (docs: "DCP feature is only available for
Ins clients"), so protection is: (1) the stop-loss lives on the exchange from the
fill, (2) this watchdog cancels *entry* orders and asks for reduce-only when a
liveness source goes silent. It never touches stops.

Liveness sources (each armed by its first beat):
  desk        — the desk heartbeat written every tick;
  ws_private  — pybit `WebSocket.is_connected()` sampled by the signer loop, not
                event frames: Bybit private topics are event-driven and can be
                silent for hours while the socket is healthy (audit B1);
  rest        — the last successful REST reconcile.

Episodes: a source that goes stale fires once; when it recovers and goes stale
again, it fires again (the old `fired[-1] == reason` check silenced every second
episode for the life of the process).
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
    on_recover: Callable[[str], None] | None = None
    max_clock_skew_ms: int = 2000
    _last: dict[str, datetime] = field(default_factory=dict)
    _in_episode: set[str] = field(default_factory=set)
    fired: list[tuple[datetime, str]] = field(default_factory=list)
    recovered: list[tuple[datetime, str]] = field(default_factory=list)
    armed: bool = False
    clock_skew_ms: int | None = None

    def __post_init__(self) -> None:
        if self.dead_man_s <= 0:
            raise ValueError("dead_man_s must be > 0")

    def beat(self, source: str, now: datetime) -> None:
        """desk | ws_private | rest. Arms on the first beat of each source."""
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
        """Cancel entries once per stale *episode* per source; stops stay on the venue."""
        if not self.armed:
            return []
        when = require_utc(now)
        stale = set(self.stale(when))
        new = sorted(stale - self._in_episode)
        healed = sorted(self._in_episode - stale)
        for src in healed:
            self._in_episode.discard(src)
            self.recovered.append((when, src))
            if self.on_recover is not None:
                self.on_recover(src)
        if new:
            reason = "dead_man:" + ",".join(new)
            self.cancel_entries(reason)
            self.fired.append((when, reason))
            self._in_episode.update(new)
        return sorted(stale)

    @property
    def in_episode(self) -> list[str]:
        return sorted(self._in_episode)
