"""1.5.4 — desk window 16:30–19:30 Europe/Moscow.

PHASE-BUILD: MSK has no DST since 2014 → 13:30–16:30 UTC every day.
We convert with zoneinfo, not a handwritten UTC offset.
Night 5x is always reject. no_us_today is an explicit logged bypass of the window.
US-data day (CPI/FOMC/NFP/PCE, same America/New_York date, known_at ≤ now)
blocks until the Moscow session opens. 24h pre-event cut is 2.11.7, not here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.types import require_utc

TIME_KEYS = frozenset(
    {
        "session_tz",
        "session_start",
        "session_end",
        "us_tz",
        "us_data_classes",
        "fomc_blackout_et",
        "event_windows",
        "pre_event_hours",
        "pre_event_size_mult",
        "first_minute_s",
        "dead_man_s",
        "reconcile_s",
    }
)


def _find_time_yaml() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "time.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/time.yaml missing")


def load_time_config() -> dict:
    raw = yaml.safe_load(_find_time_yaml().read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("time.yaml must be a mapping")
    extra = set(raw) - TIME_KEYS
    if extra:
        raise ValueError(f"unknown time.yaml keys: {sorted(extra)}")
    missing = TIME_KEYS - set(raw)
    if missing:
        raise ValueError(f"missing time.yaml keys: {sorted(missing)}")
    return raw


_CFG = load_time_config()
MSK = ZoneInfo(str(_CFG["session_tz"]))
NY = ZoneInfo(str(_CFG["us_tz"]))
START = time.fromisoformat(str(_CFG["session_start"]))
END = time.fromisoformat(str(_CFG["session_end"]))
US_MACRO = frozenset(str(x) for x in _CFG["us_data_classes"])


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


def _macro_known_at(
    now: datetime,
    calendar: Sequence[NewsRow],
    classes: frozenset[str],
) -> datetime | None:
    """known_at of a learned row in `classes` on this NY date. Else None."""
    when = require_utc(now)
    ny_day = when.astimezone(NY).date()
    for row in calendar:
        if row.event_class not in classes:
            continue
        if row.known_at > when:
            continue
        if row.event_time.astimezone(NY).date() == ny_day:
            return row.known_at
    return None


def us_data_known_at(now: datetime, calendar: Sequence[NewsRow]) -> datetime | None:
    """known_at of a US-macro row on this NY date, already learned. Else None.

    A calendar file we ingested last month is not 'news' on a quiet day.
    Same clock as us_data_day.
    """
    return _macro_known_at(now, calendar, US_MACRO)


def us_data_day(now: datetime, calendar: Sequence[NewsRow]) -> bool:
    return us_data_known_at(now, calendar) is not None


def cpi_day(now: datetime, calendar: Sequence[NewsRow]) -> bool:
    """Card CPI window: CPI on this NY date, already learned. Not the 24h pre-cut."""
    return _macro_known_at(now, calendar, frozenset({"CPI"})) is not None


class SessionWindow:
    def allows(
        self,
        now_utc: datetime,
        calendar: Sequence[NewsRow] | None = None,
        *,
        lev: Decimal = Decimal("3"),
        no_us_today: bool = False,
    ) -> tuple[bool, str]:
        if us_data_day(now_utc, calendar or ()) and not in_desk_window(now_utc):
            return False, "us_data_day"
        return allow_entry(now_utc, lev=lev, no_us_today=no_us_today)
