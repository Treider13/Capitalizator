"""1.5.4 — desk window 16:30–19:30 Europe/Moscow.

PHASE-BUILD: MSK has no DST since 2014 → 13:30–16:30 UTC every day.
We convert with zoneinfo, not a handwritten +3.
Night 5x is always reject. no_us_today is an explicit logged bypass of the window.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from capitalizator.types import require_utc

MSK = ZoneInfo("Europe/Moscow")
START = time(16, 30)
END = time(19, 30)


def in_desk_window(now: datetime) -> bool:
    local = require_utc(now).astimezone(MSK)
    stamp = local.timetz().replace(tzinfo=None)
    return START <= stamp < END


def allow_entry(
    now: datetime,
    *,
    lev: Decimal = Decimal("3"),
    no_us_today: bool = False,
) -> tuple[bool, str]:
    if lev >= 5 and not in_desk_window(now):
        return False, "night 5x"
    if in_desk_window(now):
        return True, "session"
    if no_us_today:
        return True, "no_us_today"
    return False, "outside session"
