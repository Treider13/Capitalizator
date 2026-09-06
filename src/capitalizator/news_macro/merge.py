"""One calendar for the screen, the card, and propose(). No sockets.

Scheduled classes (CPI/FOMC/NFP/PCE) take their *clock* only from the CSV
ingest (BLS/Fed/BEA). An intel headline that classifies as CPI does not create
a second event_time — RSS fetch time is not 08:30 ET.

Surprise classes (HACK/SEC/LISTING/ETF/OTHER-negative) have no CSV row; intel
*is* the calendar for those.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.types import require_utc

SCHEDULED_CLASSES = frozenset({"CPI", "FOMC", "NFP", "PCE"})
SURPRISE_CLASSES = frozenset({"HACK", "SEC", "LISTING", "ETF", "OTHER"})
INTEL_EVERY_S = 300
INTEL_STALE_S = 900
_NY = ZoneInfo("America/New_York")
_OTHER_NEG = ("hack", "exploit", "sec ", "lawsuit", "ban", "halt", "delist", "outage")


def merged_calendar(
    *,
    csv: Sequence[NewsRow],
    intel: Sequence[NewsRow],
    now: datetime | None = None,
) -> tuple[NewsRow, ...]:
    """Gate clock: official CSV rows + intel surprises. No second scheduled time."""
    if now is not None:
        require_utc(now)
    out: list[NewsRow] = []
    seen: set[str] = set()
    for row in csv:
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        out.append(row)
    for row in intel:
        if row.event_id in seen:
            continue
        if row.event_class in SCHEDULED_CLASSES:
            continue
        if not _intel_is_surprise(row):
            continue
        seen.add(row.event_id)
        out.append(row)
    return tuple(out)


def screen_events(
    *,
    csv: Sequence[NewsRow],
    intel: Sequence[NewsRow],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """CSV clocks plus intel surprises plus scheduled headlines (text only)."""
    if now is not None:
        require_utc(now)
    csv_dates = {
        (row.event_class, row.event_time.astimezone(_NY).date())
        for row in csv
        if row.event_class in SCHEDULED_CLASSES
    }
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in csv:
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        events.append(_event(row, origin="csv", clock="csv"))
    for row in intel:
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        if row.event_class in SCHEDULED_CLASSES:
            ny_day = row.event_time.astimezone(_NY).date()
            clock = "csv" if (row.event_class, ny_day) in csv_dates else "none"
            events.append(_event(row, origin="intel", clock=clock, kind="intel_headline"))
        elif _intel_is_surprise(row):
            events.append(_event(row, origin="intel", clock="intel"))
    return events


def _intel_is_surprise(row: NewsRow) -> bool:
    if row.event_class not in SURPRISE_CLASSES:
        return False
    if row.event_class != "OTHER":
        return True
    text = f"{row.notes} {row.raw}".lower()
    return any(token in text for token in _OTHER_NEG)


def heartbeat_view(
    raw: str | None, *, now: datetime, every_s: int = INTEL_EVERY_S, stale_s: int = INTEL_STALE_S
) -> dict[str, Any]:
    """Missing heartbeat is stale, not 'quiet therefore tradable'."""
    when = require_utc(now)
    age: int | None = None
    if raw:
        try:
            stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamped.tzinfo is None:
                raise ValueError("heartbeat must be UTC")
            age = max(0, int((when - require_utc(stamped)).total_seconds()))
        except (TypeError, ValueError):
            age = None
    stale = age is None or age > stale_s
    return {
        "every_s": every_s,
        "intel_heartbeat": raw,
        "heartbeat_age_s": age,
        "stale": stale,
    }


def _event(
    row: NewsRow, *, origin: str, clock: str, kind: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_id": row.event_id,
        "class": row.event_class,
        "event_time": row.event_time.isoformat(),
        "known_at": row.known_at.isoformat(),
        "assets": list(row.assets),
        "source": row.source,
        "notes": row.notes,
        "origin": origin,
        "clock": clock,
    }
    if kind is not None:
        payload["kind"] = kind
    return payload
