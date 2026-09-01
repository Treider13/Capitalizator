"""0.4.1 — calendar rows with event_time and known_at. No TG scrape.

CSV columns: PHASE-BUILD «Входные календари».
known_at is when *we* learned the row. Do not copy event_time after the fact.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from capitalizator.types import require_utc

NEWS_CLASSES = frozenset(
    {"CPI", "FOMC", "NFP", "PCE", "SEC", "LISTING", "HACK", "ETF", "OTHER"}
)
MACRO_ENV = "CAPITALIZATOR_MACRO_CSV"

REQUIRED = (
    "event_id",
    "class",
    "event_time_utc",
    "announce_tz",
    "known_at_utc",
    "assets",
    "source",
    "size_rule",
    "notes",
)


@dataclass(frozen=True)
class NewsRow:
    event_id: str
    event_class: str
    event_time: datetime
    known_at: datetime
    assets: tuple[str, ...]
    source: str
    announce_tz: str
    size_rule: str
    notes: str
    raw: str
    our_reaction_coef: None = None


class NewsIngestError(ValueError):
    """Calendar row is missing times or uses an unknown class."""


class NewsIngest:
    def __init__(self, rows: Sequence[NewsRow]) -> None:
        self.rows = list(rows)

    @classmethod
    def from_csv(cls, path: Path | str) -> NewsIngest:
        text = Path(path).read_text(encoding="utf-8")
        reader = csv.DictReader(
            line for line in text.splitlines() if line.strip() and not line.startswith("#")
        )
        if reader.fieldnames is None:
            raise NewsIngestError("csv has no header")
        missing = [k for k in REQUIRED if k not in reader.fieldnames]
        if missing:
            raise NewsIngestError(f"missing columns: {missing}")
        extra = sorted(set(reader.fieldnames) - set(REQUIRED))
        if extra:
            raise NewsIngestError(f"unknown columns: {extra}")
        rows: list[NewsRow] = []
        for i, raw in enumerate(reader, start=2):
            rows.append(_parse_row(raw, line=i))
        if not rows:
            raise NewsIngestError("csv has no events")
        return cls(rows)

    def visible(self, as_of: datetime) -> list[NewsRow]:
        when = require_utc(as_of)
        return [r for r in self.rows if r.known_at <= when]


def default_macro_path() -> Path | None:
    """`CAPITALIZATOR_MACRO_CSV` or the repo `infra/calendars/macro.csv`."""
    env = (os.environ.get(MACRO_ENV) or "").strip()
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "calendars" / "macro.csv"
        if candidate.is_file():
            return candidate
    return None


def load_desk_calendar(path: Path | str | None = None) -> tuple[NewsRow, ...]:
    """Official macro rows for the desk. Missing file → empty (honest)."""
    loc = Path(path) if path is not None else default_macro_path()
    if loc is None or not loc.is_file():
        return ()
    return tuple(NewsIngest.from_csv(loc).rows)


def _parse_row(raw: dict[str, str], *, line: int) -> NewsRow:
    event_id = (raw.get("event_id") or "").strip()
    if not event_id:
        raise NewsIngestError(f"line {line}: event_id is required")
    klass = (raw.get("class") or "").strip()
    if klass not in NEWS_CLASSES:
        raise NewsIngestError(f"line {line}: unknown class {klass!r}")
    event_time = _utc(raw.get("event_time_utc"), field="event_time_utc", line=line)
    known_at = _utc(raw.get("known_at_utc"), field="known_at_utc", line=line)
    assets = tuple(a for a in (raw.get("assets") or "").split(";") if a)
    return NewsRow(
        event_id=event_id,
        event_class=klass,
        event_time=event_time,
        known_at=known_at,
        assets=assets,
        source=(raw.get("source") or "").strip(),
        announce_tz=(raw.get("announce_tz") or "").strip(),
        size_rule=(raw.get("size_rule") or "").strip(),
        notes=(raw.get("notes") or "").strip(),
        raw=",".join(raw.get(k, "") for k in REQUIRED),
    )


def _utc(value: str | None, *, field: str, line: int) -> datetime:
    text = (value or "").strip()
    if not text:
        raise NewsIngestError(f"line {line}: {field} is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NewsIngestError(f"line {line}: bad {field} {value!r}") from exc
    if parsed.tzinfo is None:
        raise NewsIngestError(f"line {line}: {field} must be UTC (Z)")
    return require_utc(parsed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load infra/calendars/macro.csv. No scrape.")
    parser.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    news = NewsIngest.from_csv(args.file)
    print(f"n={len(news.rows)}")
    for row in news.rows:
        event = row.event_time.isoformat()
        known = row.known_at.isoformat()
        print(f"{row.event_id} {row.event_class} event={event} known={known}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
