"""2.9.2 — BTC break = working-TF close beyond the zone AND tape_eaten.

A wick through the band is not a break. This is a label, not BtcVeto.
Does not reject an alt. Does not open size.
"""

from __future__ import annotations

from datetime import datetime

from capitalizator.types import require_utc
from capitalizator.zones.config import load_registry
from capitalizator.zones.model import Bar, Zone


class Break:
    @staticmethod
    def detect(
        *,
        zone: Zone,
        bar: Bar,
        tape_eaten: bool,
        t: datetime,
        working_tf: str | None = None,
    ) -> bool:
        when = require_utc(t)
        tf = working_tf or load_registry().working_tf
        if zone.symbol != "BTCUSDT" or bar.symbol != "BTCUSDT":
            return False
        if bar.tf != tf:
            return False
        if bar.close_ts >= when:
            return False
        if not tape_eaten:
            return False
        if zone.side == "support":
            return bar.close < zone.lo
        return bar.close > zone.hi
