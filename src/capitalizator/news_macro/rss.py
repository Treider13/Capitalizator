"""Official RSS only. Telegram / scrape URLs are refused. No network in tests.

Caller passes already-fetched XML. This module does not open sockets.
"""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

from capitalizator.news_macro.ingest import NEWS_CLASSES, NewsRow
from capitalizator.types import require_utc

FORBIDDEN_HOSTS = ("t.me", "telegram", "discord.com")


def refuse_url(url: str) -> None:
    low = url.lower()
    if any(host in low for host in FORBIDDEN_HOSTS) or low.startswith("telegram"):
        raise ValueError("telegram/scrape feeds are forbidden")
    if not low.startswith("https://"):
        raise ValueError("feed url must be https")


def parse_rss(
    xml: str,
    *,
    source: str,
    known_at: datetime,
    default_assets: str = "BTCUSDT",
) -> list[NewsRow]:
    require_utc(known_at)
    refuse_url(source if "://" in source else f"https://{source}")
    root = ElementTree.fromstring(xml)
    items = list(root.iter("item"))
    rows: list[NewsRow] = []
    for i, item in enumerate(items, start=1):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or source).strip()
        refuse_url(link if "://" in link else source)
        klass = classify_title(title)
        event_id = f"rss-{source.split('/')[-1]}-{i}"
        rows.append(
            NewsRow(
                event_id=event_id,
                event_class=klass,
                event_time=known_at,
                known_at=known_at,
                assets=tuple(default_assets.split(";")),
                source=source,
                announce_tz="UTC",
                size_rule="rss",
                notes=title[:200],
                raw=title,
            )
        )
    return rows


def classify_title(title: str) -> str:
    low = title.lower()
    if "fomc" in low or "powell" in low or "federal reserve" in low:
        return "FOMC"
    if "cpi" in low:
        return "CPI"
    if "hack" in low or "exploit" in low:
        return "HACK"
    if "list" in low:
        return "LISTING"
    if "etf" in low:
        return "ETF"
    if "sec" in low:
        return "SEC"
    return "OTHER" if "OTHER" in NEWS_CLASSES else "FOMC"
