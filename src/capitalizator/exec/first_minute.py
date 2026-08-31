"""3.13.2 paper — first 60s after a breakout bar close is reject.

PHASE-BUILD: exchange_ts < breakout_bar_close_ts + first_minute_s.
Seconds come from infra/time.yaml. This is not a bounce gate.
Does not send an order. Does not invent a breakout.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from capitalizator.risk.session import load_time_config
from capitalizator.types import require_utc


class FirstMinute:
    def __init__(self, seconds: int | None = None) -> None:
        cfg = int(load_time_config()["first_minute_s"])
        self.seconds = cfg if seconds is None else seconds
        if self.seconds <= 0:
            raise ValueError("first_minute_s must be > 0")

    def blocks(self, exchange_ts: datetime, close_ts: datetime) -> bool:
        when = require_utc(exchange_ts)
        close = require_utc(close_ts)
        return when < close + timedelta(seconds=self.seconds)
