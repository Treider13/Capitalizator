"""Named Moscow sessions for the journal. Not an entry."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from capitalizator.types import require_utc

MSK = ZoneInfo("Europe/Moscow")


def session_name(now: datetime) -> str:
    local = require_utc(now).astimezone(MSK).timetz().replace(tzinfo=None)
    if time(3, 0) <= local < time(10, 0):
        return "asia"
    if time(10, 0) <= local < time(11, 0):
        return "london_open"
    if time(16, 0) <= local < time(16, 30):
        return "us_data_chaos"
    if time(16, 30) <= local < time(19, 30):
        return "desk"
    return "night"
