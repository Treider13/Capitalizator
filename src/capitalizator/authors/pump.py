"""P8 — allow-list author pump. No sockets. Telegram refused. Whales never enter.

Caller passes already-fetched items. Empty sources.yaml stays empty.
Author voice is never accept. Sole whale claim → hold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from capitalizator.authors.score import author_accepts
from capitalizator.authors.sources import SourceBook
from capitalizator.card.live import CardLive, VolumeSnapshot
from capitalizator.news_macro.rss import refuse_url
from capitalizator.types import require_utc
from capitalizator.whales.no_single import sole_whale


@dataclass(frozen=True)
class FetchedItem:
    source_id: str
    kind: str
    url: str
    title: str
    body: str
    known_at: datetime


def _claim(item: FetchedItem) -> dict[str, str]:
    text = f"{item.title} {item.body}".lower()
    if "whale" in text or "wallet" in text or "0x" in text:
        return {"type": "whale", "value": item.title[:80]}
    return {"type": "author", "value": item.title[:80]}


def pump(
    *,
    symbol: str,
    now: datetime,
    book: SourceBook,
    fetched: Sequence[FetchedItem],
    volume: VolumeSnapshot | None = None,
) -> CardLive | None:
    """Build a B card from allow-listed posts. None when the book is empty."""
    when = require_utc(now)
    if author_accepts(has_zone=True):
        raise RuntimeError("author voice must never accept")
    if not book.sources:
        return None
    allowed = {row.source_id: row for row in book.sources}
    for row in book.sources:
        refuse_url(row.url)
        if row.kind not in book.allowed_kinds:
            raise ValueError(f"source kind refused: {row.kind}")
    hits = [item for item in fetched if item.source_id in allowed]
    for item in hits:
        refuse_url(item.url)
        if item.kind not in book.allowed_kinds:
            raise ValueError(f"item kind refused: {item.kind}")
    claims = [_claim(item) for item in hits]
    whale_only = sole_whale(claims)
    pluses = ["allow_list_hit", "source_kind_ok"]
    minuses = ["author_never_accept"]
    if whale_only:
        pluses.append("whale_seen")
        minuses.append("whale_only")
        bearing = "hold"
    elif any(c["type"] == "whale" for c in claims):
        pluses.append("author_seen")
        minuses.append("whale_mention")
        bearing = "propose"
    elif hits:
        pluses.append("author_seen")
        minuses.append("base_rate_unknown")
        bearing = "propose"
    else:
        pluses.append("allow_list_quiet")
        minuses.append("no_author_hit")
        bearing = "hold"
    n = len(pluses) + len(minuses)
    while n < 5:
        pluses.append(f"atom_{n}")
        n = len(pluses) + len(minuses)
    return CardLive(
        symbol=symbol,
        bearing_verdict=bearing,  # type: ignore[arg-type]
        known_at=when,
        macro_multiplier=Decimal("1"),
        volume=volume or VolumeSnapshot(),
        pluses=tuple(pluses[: max(0, 7 - len(minuses))]),
        minuses=tuple(minuses),
    )
