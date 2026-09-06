"""Timestamped official news ingestion; text never issues trading commands."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from capitalizator.fusion.store import Store
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.merge import merged_calendar
from capitalizator.news_macro.rss import classify_title

URL = "https://api.bybit.com/v5/announcements/index?locale=en-US&limit=20"
NEGATIVE = frozenset(
    {
        "hack",
        "exploit",
        "outage",
        "halt",
        "suspend",
        "suspension",
        "delist",
        "delisting",
        "lawsuit",
        "breach",
        "maintenance",
    }
)
POSITIVE = frozenset({"resumed", "restored", "resolved", "approved", "approval"})


def sentiment(text: str) -> float:
    """Transparent lexicon score used only as a surprise-risk filter, not an alpha."""
    words = re.findall(r"[a-z]+", text.lower())
    values = []
    for i, word in enumerate(words):
        score = 1 if word in POSITIVE else -1 if word in NEGATIVE else 0
        if i and words[i - 1] in {"no", "not", "without"}:
            score = -score
        if score:
            values.append(score)
    return sum(values) / len(values) if values else 0.0


def fetch(timeout: float = 5.0) -> dict[str, Any]:
    from capitalizator.fusion.external import read_url

    raw = read_url(URL, timeout)
    body = json.loads(raw)
    if body.get("retCode") != 0:
        raise ValueError("news endpoint rejected request")
    return dict(body)


def ingest(store: Store, payload: dict[str, Any], at: float) -> list[NewsRow]:
    seen = store.meta("news_seen", {})
    results = []
    for item in payload.get("result", {}).get("list", []):
        title = str(item.get("title") or "")
        description = str(item.get("description") or "")
        url = str(item.get("url") or URL)
        published = float(item.get("dateTimestamp") or 0) / 1000
        if published <= 0 or published > at:
            continue
        ident = hashlib.sha256((url + title + str(published)).encode()).hexdigest()[:24]
        known = float(seen.setdefault(ident, at))
        value = sentiment(title + " " + description)
        classification = classify_title(title)
        store.put_meta(
            "news_item:" + ident,
            {
                "title": title,
                "url": url,
                "published": published,
                "known_at": known,
                "sentiment": value,
                "class": classification,
            },
        )
        # Old announcements discovered on startup are recorded, not fresh shocks.
        if value >= 0 or at - published > 3600 or at - known > 3600:
            continue
        when = datetime.fromtimestamp(known, UTC)
        results.append(
            NewsRow(
                ident,
                classification,
                when,
                when,
                ("ALL",),
                url,
                "UTC",
                "surprise_blackout",
                title,
                title,
            )
        )
    # Bound dedup memory; persisted item identities retain audit provenance.
    seen = dict(sorted(seen.items(), key=lambda r: r[1])[-10000:])
    store.put_meta("news_seen", seen)
    store.put_meta("news_status", {"at": at, "ok": True, "surprises": len(results)})
    return results


def calendar(base: tuple[NewsRow, ...], surprises: list[NewsRow]) -> tuple[NewsRow, ...]:
    # Fusion adapters already classify these records. The legacy text filter
    # drops unlocks and even negative vocabulary such as "breach"/"suspension".
    typed = {"unlock_blackout", "linear_supply_context", "surprise_blackout"}
    accepted = [r for r in surprises if r.size_rule in typed]
    remaining = [r for r in surprises if r.size_rule not in typed]
    rows = {r.event_id: r for r in merged_calendar(csv=base, intel=remaining)}
    for row in accepted:
        rows.setdefault(row.event_id, row)
    return tuple(sorted(rows.values(), key=lambda r: (r.event_time, r.event_id)))


def protect(
    store: Store,
    rows: tuple[NewsRow, ...],
    mode: str,
    symbols: tuple[str, ...],
    at: float,
    post_minutes: int,
) -> None:
    """The same source-time risk action in the live broker and event replay."""
    accounts = store.rows("SELECT body FROM account WHERE mode=?", (mode,))
    positions = (
        {
            p["symbol"]
            for p in json.loads(accounts[0]["body"])["positions"]
            if float(p.get("size") or 0)
        }
        if accounts
        else set()
    )
    for symbol in symbols:
        if not any(
            r.size_rule == "surprise_blackout"
            and (not r.assets or "ALL" in r.assets or symbol in r.assets)
            and r.known_at.timestamp() <= at <= r.event_time.timestamp() + post_minutes * 60
            for r in rows
        ):
            continue
        orders = store.rows(
            "SELECT * FROM orders WHERE mode=? AND symbol=? "
            "AND state NOT IN ('closed','rejected') ORDER BY created DESC LIMIT 1",
            (mode, symbol),
        )
        if orders:
            order = orders[0]
            if order["state"] == "cancelled" and symbol not in positions:
                continue
            store.command(
                "news-exit-" + order["id"], mode, symbol, "flatten", at, {"reason": "news_surprise"}
            )
            with store.transaction() as db:
                db.execute(
                    "UPDATE contracts SET state='refuted',updated=? WHERE id=?",
                    (at, order["contract"]),
                )
