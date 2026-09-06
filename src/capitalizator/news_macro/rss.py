"""Official RSS only. Telegram / scrape URLs are refused. No network in tests.

Caller passes already-fetched XML. This module does not open sockets.
"""

from __future__ import annotations

import re
from datetime import datetime
from xml.etree import ElementTree

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.types import require_utc

_FOMC = re.compile(r"fomc|powell|federal\s+reserve", re.I)
_CPI = re.compile(r"\bcpi\b", re.I)
_NFP = re.compile(r"\b(nfp|non[\s-]?farm|payrolls?)\b", re.I)
_PCE = re.compile(r"\b(pce|personal\s+consumption)\b", re.I)
_HACK = re.compile(r"hack|exploit", re.I)
_LISTING = re.compile(r"\b(listing|listed|lists|will\s+list)\b", re.I)
_ETF = re.compile(r"\betf\b", re.I)
_SEC = re.compile(r"\bsec\b", re.I)

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
    """Official tokens only. Unknown → OTHER, never a silent FOMC.

    NFP/PCE are classified *before* LISTING so payrolls cannot match `list`.
    Listing needs a word (`listing` / `lists` / `will list`), not a substring.
    """
    if _FOMC.search(title):
        return "FOMC"
    if _CPI.search(title):
        return "CPI"
    if _NFP.search(title):
        return "NFP"
    if _PCE.search(title):
        return "PCE"
    if _HACK.search(title):
        return "HACK"
    if _LISTING.search(title):
        return "LISTING"
    if _ETF.search(title):
        return "ETF"
    if _SEC.search(title):
        return "SEC"
    return "OTHER"
