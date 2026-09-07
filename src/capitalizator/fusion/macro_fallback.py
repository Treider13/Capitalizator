"""Fail-closed CPI/NFP calendar from the New York Fed's published monthly tables."""

from __future__ import annotations

import calendar
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from capitalizator.fusion.external import read_url
from capitalizator.news_macro.ingest import NewsRow

URL = "https://www.newyorkfed.org/research/calendars/nationalecon_cal.html"
TITLES = {"Consumer Price Index": "CPI", "Employment Situation": "NFP"}


class CalendarPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[tuple[str, list[str]]] = []
        self.cell: tuple[str, list[str]] | None = None
        self.next_links: list[str] = []
        self.link: str | None = None
        self.link_text: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "td":
            classes = (attributes.get("class") or "").split()
            kind = "heading" if "ts-data-table-head" in classes else "day"
            if kind == "heading" or "somatdR" in classes:
                if self.cell is not None:
                    raise ValueError("nested NY Fed calendar cell")
                self.cell = (kind, [])
        if tag == "a":
            self.link, self.link_text = attributes.get("href"), []

    def handle_data(self, data: str) -> None:
        parts = [p.strip() for p in data.splitlines() if p.strip()]
        self.text.extend(parts)
        if self.cell is not None:
            self.cell[1].extend(parts)
        if self.link is not None:
            self.link_text.extend(parts)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell is not None:
            self.cells.append(self.cell)
            self.cell = None
        if tag == "a":
            if self.link and " ".join(self.link_text).strip() == "NEXT MONTH":
                self.next_links.append(self.link)
            self.link = None


def parse_month(
    body: bytes,
    source: str,
    at: float,
    expected: tuple[int, int],
    *,
    require_next_link: bool = True,
) -> tuple[list[NewsRow], str | None]:
    # Import locally: macro owns the common event schema and timezone conversion.
    from capitalizator.fusion.macro import NY, row

    page = CalendarPage()
    page.feed(body.decode("utf-8"))
    page.close()
    if page.cell is not None or "all Eastern Time" not in " ".join(page.text):
        raise ValueError("incomplete NY Fed calendar or missing timezone")
    year, month = expected
    headings = [" ".join(parts) for kind, parts in page.cells if kind == "heading"]
    if headings != [f"{calendar.month_name[month]} {year}"]:
        raise ValueError("NY Fed calendar month mismatch")
    next_url = None
    # Only validate navigation when another page will actually be fetched.
    if require_next_link:
        if len(page.next_links) != 1:
            raise ValueError("NY Fed next month link missing or ambiguous")
        next_url = urljoin(source, page.next_links[0])
        target = urlparse(next_url)
        if (
            target.scheme != "https"
            or target.netloc != "www.newyorkfed.org"
            or not re.fullmatch(r"/research/calendars/i-[a-z]{3}\d{2}\.html", target.path)
            or target.query
            or target.fragment
        ):
            raise ValueError("invalid NY Fed next month URL")
    result = []
    seen = set()
    for kind, parts in page.cells:
        if kind != "day" or not parts:
            continue
        if not re.fullmatch(r"\d{1,2}", parts[0]):
            raise ValueError("NY Fed calendar day missing")
        day = int(parts[0])
        for i, title in enumerate(parts):
            if title not in TITLES:
                continue
            stamp = (
                re.fullmatch(r"\((\d{2}):(\d{2})\)", parts[i + 1]) if i + 1 < len(parts) else None
            )
            if stamp is None:
                raise ValueError("NY Fed release time missing or ambiguous")
            when = datetime(year, month, day, int(stamp[1]), int(stamp[2]), tzinfo=NY)
            event_class = TITLES[title]
            if event_class in seen:
                raise ValueError("duplicate NY Fed monthly release")
            seen.add(event_class)
            result.append(row(event_class, when, at, source, title))
    if seen != set(TITLES.values()):
        raise ValueError("NY Fed monthly CPI/NFP coverage incomplete")
    return result, next_url


def fetch(timeout: float, at: float) -> list[NewsRow]:
    from capitalizator.fusion.macro import NY

    now = datetime.fromtimestamp(at, NY)
    current = (now.year, now.month)
    following = (now.year + (now.month == 12), now.month % 12 + 1)
    rows, next_url = parse_month(read_url(URL, timeout), URL, at, current)
    if next_url is None:
        raise ValueError("NY Fed next month link missing")
    future_rows, _ = parse_month(
        read_url(next_url, timeout), next_url, at, following, require_next_link=False
    )
    rows.extend(future_rows)
    if not all(
        any(r.event_class == k and r.event_time.timestamp() > at for r in rows)
        for k in TITLES.values()
    ):
        raise ValueError("NY Fed future CPI/NFP coverage incomplete")
    return rows
