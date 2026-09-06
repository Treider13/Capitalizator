"""Bounded read-only public data adapters, independent of the account writer."""

from __future__ import annotations

import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from capitalizator.fusion.news import sentiment
from capitalizator.news_macro.ingest import NewsRow


def read_url(url: str, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    if urlparse(url).scheme != "https":
        raise ValueError("external sources require HTTPS")
    request = Request(url, headers={"User-Agent": "Capitalizator/1.0", **(headers or {})})
    deadline = time.monotonic() + timeout
    body = bytearray()
    with urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read1(65536)
            if time.monotonic() > deadline:
                raise TimeoutError("external total response deadline")
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > 2_000_000:
                raise ValueError("external response exceeds 2MB budget")
    return bytes(body)


def bybit(path: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.loads(
        read_url("https://api.bybit.com/v5/" + path + "?" + urlencode(params), timeout)
    )
    if body.get("retCode") != 0:
        raise ValueError("public Bybit request rejected")
    return dict(body["result"])


def gamma(rows: list[dict[str, Any]], at: float) -> dict[str, Any]:
    strikes: dict[float, float] = {}
    total_oi = weighted_iv = gross = 0.0
    for row in rows:
        if row.get("openInterest") in (None, ""):
            raise ValueError("missing option open interest")
        oi = float(row["openInterest"])
        if not math.isfinite(oi) or oi < 0:
            raise ValueError("invalid option open interest")
        if not oi:
            continue
        if any(row.get(k) in (None, "") for k in ("gamma", "underlyingPrice", "markIv")):
            raise ValueError("missing option Greeks or valuation")
        g, price, iv = (float(row[k]) for k in ("gamma", "underlyingPrice", "markIv"))
        if not all(math.isfinite(v) for v in (g, price, iv)) or g < 0 or min(price, iv) <= 0:
            raise ValueError("invalid option data")
        strike = float(str(row["symbol"]).split("-")[2])
        if not math.isfinite(strike) or strike <= 0:
            raise ValueError("invalid option strike")
        value = g * oi * price * price * 0.01
        gross += value
        total_oi += oi
        weighted_iv += oi * iv
        strikes[strike] = strikes.get(strike, 0) + value
    return {
        "at": at,
        "available": bool(total_oi),
        "gross_gamma_1pct": gross if total_oi else None,
        "oi": total_oi,
        "weighted_iv": weighted_iv / total_oi if total_oi else None,
        "strikes": [{"price": p, "gross": v} for p, v in sorted(strikes.items())],
        "source": "Bybit option tickers",
        "dealer_sign": "unknown",
        "units": "USD delta-notional proxy per 1% move; assumes OI in underlying units",
    }


def timestamp(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = parsedate_to_datetime(value)
    if dt.tzinfo is None:
        raise ValueError("source timestamp requires timezone")
    return dt.astimezone(UTC)


def rss(body: bytes, source: dict[str, Any], at: float) -> list[dict[str, Any]]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("XML entities are forbidden")
    root = ET.fromstring(body)
    if root.tag.split("}")[-1] not in {"rss", "feed", "RDF"}:
        raise ValueError("response is not an RSS/Atom feed")
    result = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        fields = {n.tag.split("}")[-1]: n for n in node}

        def value(key: str) -> str:
            return "".join(fields[key].itertext()).strip() if key in fields else ""

        date = value("pubDate") or value("published") or value("updated") or value("date")
        if not date:
            continue
        published = timestamp(date).timestamp()
        if published > at:
            continue
        link = fields.get("link")
        url = (link.attrib.get("href") or value("link")) if link is not None else source["url"]
        title = value("title")
        result.append(
            {
                "id": hashlib.sha256(
                    (source["name"] + url + title + str(published)).encode()
                ).hexdigest()[:24],
                "title": title,
                "url": url,
                "published": published,
                "assets": list(source["assets"]),
                "sentiment": sentiment(title + " " + value("description")),
                "source": source["name"],
            }
        )
    return result


def unlocks(payload: dict[str, Any], source: dict[str, Any], at: float) -> list[NewsRow]:
    if payload.get("status") is not True:
        raise ValueError("unlock provider rejected request")
    out = []
    now = datetime.fromtimestamp(at, UTC)
    for row in payload.get("data", []):
        # AI-extracted/month-level dates must never masquerade as exact event times.
        if row.get("listedMethod") == "AI":
            raise ValueError("unlock date requires verified source")
        linear = row.get("linearUnlocks") or {}
        if float(linear.get("dailyAmount") or 0) > 0:
            # Continuous issuance is context, never an invented minute-level shock.
            ident = hashlib.sha256(
                (source["name"] + row["unlockDate"] + ":linear").encode()
            ).hexdigest()[:24]
            out.append(
                NewsRow(
                    ident,
                    "OTHER",
                    timestamp(row["unlockDate"]),
                    now,
                    tuple(source["assets"]),
                    "https://tokenomist.ai/" + source["token_id"],
                    "UTC",
                    "linear_supply_context",
                    "Continuous token supply (not a discrete event)",
                    json.dumps(linear),
                )
            )
        cliff = row.get("cliffUnlocks") or {}
        if not float(cliff.get("cliffAmount") or 0):
            continue
        breakdown = cliff.get("allocationBreakdown") or []
        if not breakdown or any(v.get("unlockPrecision") != "second" for v in breakdown):
            raise ValueError("unlock timestamp precision insufficient for minute blackout")
        when = timestamp(row["unlockDate"])
        ident = hashlib.sha256((source["name"] + row["unlockDate"]).encode()).hexdigest()[:24]
        out.append(
            NewsRow(
                ident,
                "OTHER",
                when,
                now,
                tuple(source["assets"]),
                "https://tokenomist.ai/" + source["token_id"],
                "UTC",
                "unlock_blackout",
                "Token unlock " + str(row.get("tokenSymbol", "")),
                json.dumps(row),
            )
        )
    return out


def sources(root: Path, symbols: tuple[str, ...]) -> list[dict[str, Any]]:
    path = root / "news_sources.json"
    defaults: list[dict[str, Any]] = [
        {
            "name": "bitcoin-core",
            "kind": "rss",
            "url": "https://bitcoincore.org/en/rss.xml",
            "assets": ["BTCUSDT"],
        },
        {
            "name": "ethereum-foundation",
            "kind": "rss",
            "url": "https://blog.ethereum.org/feed.xml",
            "assets": ["ETHUSDT"],
        },
    ]
    rows = (
        json.loads(path.read_text())
        if path.exists()
        else [r for r in defaults if set(r["assets"]) & set(symbols)]
    )
    return validate_sources(rows, symbols)


def validate_sources(rows: Any, symbols: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError("news_sources must be a list of at most 32 sources")
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("source name required")
        if row.get("kind") not in {"rss", "unlocks"}:
            raise ValueError("unsupported source kind")
        if row["name"] in names or row["kind"] not in {"rss", "unlocks"}:
            raise ValueError("duplicate source or unsupported adapter")
        names.add(row["name"])
        assets = row.get("assets")
        if (
            not isinstance(assets, list)
            or not assets
            or any(not isinstance(a, str) or (a not in symbols and a != "ALL") for a in assets)
        ):
            raise ValueError("news assets must match configured symbols")
        if row["kind"] == "rss":
            url = row.get("url")
            if (
                not isinstance(url, str)
                or urlparse(url).scheme != "https"
                or not urlparse(url).hostname
            ):
                raise ValueError("news URL requires HTTPS and a hostname")
            if urlparse(url).username or urlparse(url).password:
                raise ValueError("news URL may not contain credentials")
        elif not isinstance(row.get("token_id"), str) or not row["token_id"].strip():
            raise ValueError("unlock source requires token_id")
    return [r for r in rows if "ALL" in r["assets"] or set(r["assets"]) & set(symbols)]


def fetch_source(
    source: dict[str, Any], timeout: float, at: float, key: str | None = None
) -> list[Any]:
    if source["kind"] == "rss":
        body = read_url(source["url"], timeout)
        return rss(body, source, max(at, time.time()))
    if not key:
        raise ValueError("tokenomist_credentials_missing")
    now = datetime.fromtimestamp(at, UTC)
    params = {
        "tokenId": source["token_id"],
        "start": str(now.date()),
        "end": str((now + timedelta(days=7)).date()),
    }
    payload = json.loads(
        read_url(
            "https://api.tokenomist.ai/v3/unlock/events?" + urlencode(params),
            timeout,
            {"x-api-key": key},
        )
    )
    return unlocks(payload, source, max(at, time.time()))
