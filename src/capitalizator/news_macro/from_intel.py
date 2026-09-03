"""Live intel_item rows → NewsRow calendar for Card B. No sockets. No advice.

RSS announcements already carry `event_class` from parse_rss. Reddit/X titles
are classified the same way. Unclassified OTHER without a negative token is
dropped — a headline is not a veto.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from capitalizator.news_macro.ingest import NEWS_CLASSES, NewsRow
from capitalizator.news_macro.rss import classify_title
from capitalizator.ops.knowledge import Knowledge
from capitalizator.types import require_utc

TEXT_KINDS = frozenset({"rss", "reddit", "x_account"})
HORIZON_H = 48


def row_from_item(item: Mapping[str, Any]) -> NewsRow | None:
    text = str(item.get("text") or item.get("notes") or "")
    klass = str(item.get("event_class") or classify_title(text) or "")
    if klass not in NEWS_CLASSES:
        return None
    if klass == "OTHER" and not _looks_negative(text):
        return None
    known_raw = item.get("known_at")
    if not known_raw:
        return None
    known_at = require_utc(_as_dt(known_raw))
    event_raw = item.get("event_time") or known_raw
    event_time = require_utc(_as_dt(event_raw))
    assets = _assets(item.get("assets"))
    source = str(item.get("source_id") or item.get("url") or "intel")
    return NewsRow(
        event_id=str(item.get("id") or f"intel-{known_at.isoformat()}"),
        event_class=klass,
        event_time=event_time,
        known_at=known_at,
        assets=assets,
        source=source,
        announce_tz="UTC",
        size_rule="intel",
        notes=text[:200],
        raw=text,
    )


def calendar_from_intel(
    knowledge: Knowledge, *, now: datetime, horizon_h: int = HORIZON_H
) -> tuple[NewsRow, ...]:
    if not knowledge.available():
        return ()
    when = require_utc(now)
    since = (when - timedelta(hours=horizon_h)).isoformat()
    rows: list[NewsRow] = []
    seen: set[str] = set()
    for item in knowledge.intel_items(since=since, limit=400):
        if item.get("kind") not in TEXT_KINDS:
            continue
        row = row_from_item(item)
        if row is None or row.event_id in seen:
            continue
        seen.add(row.event_id)
        rows.append(row)
    return tuple(rows)


def claims_from_intel(items: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Author/whale claims for `sole_whale`. Empty when there is no text."""
    out: list[dict[str, str]] = []
    for item in items:
        if item.get("kind") not in TEXT_KINDS:
            continue
        text = str(item.get("text") or "")
        if not text:
            continue
        low = text.lower()
        if "whale" in low or "wallet" in low or "0x" in low:
            out.append({"type": "whale", "value": text[:80]})
        else:
            out.append({"type": "author", "value": text[:80]})
    return out


def _assets(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(a for a in raw.split(";") if a)
    if isinstance(raw, (list, tuple)):
        return tuple(str(a) for a in raw if a)
    return ()


def _as_dt(raw: object) -> datetime:
    if isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _looks_negative(text: str) -> bool:
    low = text.lower()
    return any(
        token in low
        for token in ("hack", "exploit", "sec ", "lawsuit", "ban", "halt", "delist", "outage")
    )
