"""0.4.5 — silence > dead_man_s from time.yaml → cancel_all.

The callback is injected. This is the unit, not a testnet screenshot.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from capitalizator.types import require_utc


def yaml_dead_man_s() -> int:
    from capitalizator.risk.session import load_time_config

    seconds = int(load_time_config()["dead_man_s"])
    if seconds <= 0:
        raise ValueError("dead_man_s must be > 0")
    return seconds


class DeadMan:
    def __init__(
        self,
        cancel_all: Callable[[], None],
        *,
        dead_man_s: int | None = None,
    ) -> None:
        seconds = yaml_dead_man_s() if dead_man_s is None else dead_man_s
        if seconds <= 0:
            raise ValueError("dead_man_s must be > 0")
        self.dead_man_s = seconds
        self._cancel_all = cancel_all
        self._last: datetime | None = None
        self.cancelled = False

    def beat(self, now: datetime) -> None:
        self._last = require_utc(now)

    def tick(self, now: datetime) -> bool:
        when = require_utc(now)
        if self._last is None or (when - self._last).total_seconds() > self.dead_man_s:
            self._cancel_all()
            self.cancelled = True
            return True
        return False
