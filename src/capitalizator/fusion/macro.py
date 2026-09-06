"""Official schedules, receipt-time provenance and explicit coverage expiration.

BLS/BEA publish iCalendar. Fed publishes meeting dates; the scheduled policy
statement convention is 14:00 America/New_York on the final meeting day.
This is a calendar rule (not NLP inference); unscheduled decisions are news.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from capitalizator.fusion.external import read_url
from capitalizator.news_macro.ingest import NewsRow

SOURCES = {
    "bls": "https://www.bls.gov/schedule/news_release/bls.ics",
    "bea": "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics",
    "fed": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
}
CLASSES = {"bls": ("CPI", "NFP"), "bea": ("PCE",), "fed": ("FOMC",)}
NY = ZoneInfo("America/New_York")


def row(kind: str, when: datetime, at: float, source: str, title: str) -> NewsRow:
    ident = hashlib.sha256((source + kind + when.isoformat()).encode()).hexdigest()[:24]
    return NewsRow(
        ident,
        kind,
        when.astimezone(UTC),
        datetime.fromtimestamp(at, UTC),
        ("ALL",),
        source,
        "America/New_York",
        "macro_blackout",
        title,
        title,
    )


def ical(body: bytes, source: str, at: float) -> list[NewsRow]:
    text = body.decode("utf-8-sig")
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text:
        raise ValueError("not a complete iCalendar")
    # RFC 5545 folded content lines; never turn an all-day date into a precise time.
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    fields: dict[str, tuple[str, str]] | None = None
    result = []
    for line in lines:
        if line == "BEGIN:VEVENT":
            if fields is not None:
                raise ValueError("nested calendar event")
            fields = {}
        elif line == "END:VEVENT":
            if fields is None:
                raise ValueError("unmatched calendar event")
            title = fields.get("SUMMARY", ("", ""))[1]
            kind = (
                "CPI"
                if re.search(r"\bConsumer Price Index\b", title, re.I)
                else "NFP"
                if re.search(r"\bEmployment Situation\b", title, re.I)
                else "PCE"
                if re.search(r"\bPersonal Income and Outlays\b", title, re.I)
                else None
            )
            if kind and fields.get("STATUS", ("", ""))[1] != "CANCELLED":
                if any(key in fields for key in ("RRULE", "RDATE", "EXDATE")):
                    raise ValueError("recurring macro events require explicit occurrence dates")
                params, value = fields.get("DTSTART", ("", ""))
                if "VALUE=DATE" in params and "VALUE=DATE-TIME" not in params:
                    raise ValueError("macro time cannot be date-only")
                if not re.fullmatch(r"\d{8}T\d{6}Z?", value):
                    raise ValueError("macro time missing or imprecise")
                when = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
                if value.endswith("Z"):
                    when = when.replace(tzinfo=UTC)
                else:
                    match = re.search(r'(?:^|;)TZID="?([^;"\r\n]+)', params)
                    if not match:
                        raise ValueError("macro time requires timezone")
                    tz = match[1]
                    # BLS publishes US-Eastern, an alias for DST-aware New York.
                    zone = (
                        NY
                        if tz in {"US-Eastern", "US/Eastern", "Eastern Standard Time"}
                        else ZoneInfo(tz)
                    )
                    when = when.replace(tzinfo=zone)
                result.append(row(kind, when, at, source, title))
            fields = None
        elif fields is not None and ":" in line:
            key, value = line.split(":", 1)
            name, _, params = key.partition(";")
            fields[name] = (params, value.replace(r"\,", ",").replace(r"\n", " "))
    if fields is not None:
        raise ValueError("unterminated calendar event")
    if not result:
        raise ValueError("no recognized macro events")
    return result


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def handle_data(self, data: str) -> None:
        self.lines.extend(x.strip() for x in data.splitlines() if x.strip())


def fed(body: bytes, at: float) -> list[NewsRow]:
    parser = _Text()
    parser.feed(body.decode("utf-8"))
    year = None
    month = None
    months = {name: i for i, name in enumerate(calendar.month_name) if name}
    months.update({name: i for i, name in enumerate(calendar.month_abbr) if name})
    result = []
    for line in parser.lines:
        heading = re.fullmatch(r"(\d{4}) FOMC Meetings", line)
        if heading:
            year, month = int(heading[1]), None
            continue
        names = line.split("/")
        if year and all(n in months for n in names):
            month = months[names[-1]]
            continue
        days = re.fullmatch(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\*?", line)
        if year and month and days:
            day = int(days[2] or days[1])
            when = datetime(year, month, day, 14, tzinfo=NY)
            result.append(
                row(
                    "FOMC",
                    when,
                    at,
                    SOURCES["fed"],
                    "FOMC decision (published date, standard 14:00 ET release)",
                )
            )
            # The conference is a distinct scheduled risk window at 14:30 ET.
            result.append(
                row(
                    "FOMC",
                    when.replace(minute=30),
                    at,
                    SOURCES["fed"],
                    "FOMC press conference (standard 14:30 ET)",
                )
            )
        month = None
    if not result:
        raise ValueError("no recognized Fed meeting dates")
    return result


def fetch(name: str, timeout: float, at: float) -> list[NewsRow]:
    body = read_url(SOURCES[name], timeout)
    return fed(body, at) if name == "fed" else ical(body, SOURCES[name], at)


def coverage(
    rows: tuple[NewsRow, ...], health: dict[str, Any], at: float, stale: float
) -> list[str]:
    missing = []
    for name, kinds in CLASSES.items():
        status = health.get(name, {})
        if not status.get("ok") or not 0 <= at - status.get("at", 0) <= stale:
            missing.append("macro_source:" + name)
        for kind in kinds:
            if not any(
                r.event_class == kind and r.known_at.timestamp() <= at < r.event_time.timestamp()
                for r in rows
            ):
                missing.append("macro_calendar_exhausted:" + kind)
    return missing
