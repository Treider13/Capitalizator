"""Public/ToS-clean sources for contour B. Every item carries `known_at` (when WE saw it).

Sources (all read-only, no exchange keys):
  rss            official feeds (CoinDesk, The Block, Fed, SEC, Bybit announcements…), https only
  reddit         public JSON of a subreddit (`/r/<sub>/new.json`) — no scraping of HTML
  x_account      X API v2 (bearer from Settings) — recent tweets of a curated account
  hl_wallet      Hyperliquid public info API — clearinghouseState of a wallet (cohort only)
  bybit_public   Bybit v5 public: long/short account ratio, open interest, funding history
  fng            alternative.me Fear & Greed index

Transport is an injected `get(url, headers) -> bytes` / `post(url, body, headers)`, so tests
run without sockets. Nothing here decides anything: it stores raw material with a clock.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import blake2s
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from capitalizator.news_macro.rss import parse_rss, refuse_url
from capitalizator.types import require_utc

Getter = Callable[[str, dict[str, str]], bytes]
Poster = Callable[[str, bytes, dict[str, str]], bytes]
UA = "capitalizator-intel/1.0 (read-only research)"


def default_get(url: str, headers: dict[str, str]) -> bytes:
    req = Request(url, headers={"User-Agent": UA, **headers})
    with urlopen(req, timeout=15) as resp:  # noqa: S310 - https only, checked by callers
        return resp.read()


def default_post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    req = Request(url, data=body, headers={"User-Agent": UA, **headers}, method="POST")
    with urlopen(req, timeout=15) as resp:  # noqa: S310
        return resp.read()


@dataclass(frozen=True)
class IntelItem:
    id: str
    kind: str
    source_id: str
    known_at: datetime
    author_id: str
    text: str
    url: str
    published_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        return {
            "author_id": self.author_id,
            "text": self.text,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            **self.extra,
        }


def _hid(*parts: str) -> str:
    return blake2s("|".join(parts).encode(), digest_size=12).hexdigest()


def _https(url: str) -> None:
    refuse_url(url)


# --- RSS -------------------------------------------------------------------------------
def fetch_rss(url: str, *, now: datetime, get: Getter = default_get) -> list[IntelItem]:
    _https(url)
    xml = get(url, {}).decode("utf-8", errors="replace")
    rows = parse_rss(xml, source=url, known_at=require_utc(now))
    out: list[IntelItem] = []
    for row in rows:
        title = row.raw or row.notes or ""
        out.append(
            IntelItem(
                id=_hid("rss", url, title),
                kind="rss",
                source_id=f"rss:{url}",
                known_at=require_utc(now),
                author_id=url.split("/")[2],
                text=title,
                url=url,
                extra={"event_class": row.event_class},
            )
        )
    return out


# --- Reddit ---------------------------------------------------------------------------
# Reddit answers 403 "Blocked" to datacenter IPs on the public JSON (VPS, 2026-09-03).
# With a script app (client id/secret from Настройки) we use OAuth client_credentials
# and oauth.reddit.com, which is the supported path. Without credentials we still try
# the public JSON and report the 403 honestly on the source row.
def reddit_token(client_id: str, client_secret: str, *, post: Poster = default_post) -> str:
    import base64

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    raw = post(
        "https://www.reddit.com/api/v1/access_token",
        b"grant_type=client_credentials",
        {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    data = json.loads(raw.decode())
    token = data.get("access_token")
    if not token:
        raise ValueError(f"reddit token refused: {data.get('error') or data}")
    return str(token)


def fetch_reddit(
    sub: str,
    *,
    now: datetime,
    get: Getter = default_get,
    limit: int = 50,
    token: str | None = None,
) -> list[IntelItem]:
    query = urlencode({"limit": limit, "raw_json": 1})
    if token:
        url = f"https://oauth.reddit.com/r/{sub}/new?{query}"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    else:
        url = f"https://www.reddit.com/r/{sub}/new.json?{query}"
        headers = {"Accept": "application/json"}
    _https(url)
    data = json.loads(get(url, headers).decode("utf-8", errors="replace"))
    children = (((data or {}).get("data") or {}).get("children")) or []
    out: list[IntelItem] = []
    for child in children:
        d = child.get("data") or {}
        pid = str(d.get("id") or "")
        if not pid:
            continue
        created = d.get("created_utc")
        published = datetime.fromtimestamp(float(created), tz=UTC) if created else None
        text = f"{d.get('title') or ''}\n{d.get('selftext') or ''}".strip()
        out.append(
            IntelItem(
                id=_hid("reddit", sub, pid),
                kind="reddit",
                source_id=f"reddit:{sub}",
                known_at=require_utc(now),
                author_id=f"reddit:{d.get('author') or 'unknown'}",
                text=text[:4000],
                url=f"https://www.reddit.com{d.get('permalink') or ''}",
                published_at=published,
                extra={"score": d.get("score"), "num_comments": d.get("num_comments")},
            )
        )
    return out


# --- X / Twitter (official API v2) -------------------------------------------------------
def fetch_x_account(
    account: str, *, bearer: str, now: datetime, get: Getter = default_get, max_results: int = 20
) -> list[IntelItem]:
    if not bearer:
        raise ValueError("x bearer missing: X source is off")
    handle = account.lstrip("@")
    who = json.loads(
        get(
            f"https://api.x.com/2/users/by/username/{handle}",
            {"Authorization": f"Bearer {bearer}"},
        ).decode()
    )
    uid = ((who or {}).get("data") or {}).get("id")
    if not uid:
        raise ValueError(f"x user {handle} not found")
    params = urlencode(
        {
            "max_results": max(5, min(100, max_results)),
            "tweet.fields": "created_at,entities,public_metrics",
        }
    )
    auth = {"Authorization": f"Bearer {bearer}"}
    body = json.loads(get(f"https://api.x.com/2/users/{uid}/tweets?{params}", auth).decode())
    out: list[IntelItem] = []
    for tw in (body or {}).get("data") or []:
        tid = str(tw.get("id") or "")
        text = str(tw.get("text") or "")
        urls = [u.get("expanded_url", "") for u in ((tw.get("entities") or {}).get("urls") or [])]
        created = tw.get("created_at")
        published = datetime.fromisoformat(str(created).replace("Z", "+00:00")) if created else None
        out.append(
            IntelItem(
                id=_hid("x", handle, tid),
                kind="x_account",
                source_id=f"x_account:{handle}",
                known_at=require_utc(now),
                author_id=f"x:{handle}",
                text=text,
                url=f"https://x.com/{handle}/status/{tid}",
                published_at=published,
                extra={
                    "has_ref_link": any(("ref" in u or "?r=" in u or "invite" in u) for u in urls),
                    "metrics": tw.get("public_metrics") or {},
                },
            )
        )
    return out


# --- Hyperliquid (public info API) --------------------------------------------------------
HL_INFO = "https://api.hyperliquid.xyz/info"


def fetch_hl_wallet(wallet: str, *, now: datetime, post: Poster = default_post) -> IntelItem:
    body = json.dumps({"type": "clearinghouseState", "user": wallet}).encode()
    data = json.loads(post(HL_INFO, body, {"Content-Type": "application/json"}).decode())
    positions = []
    for row in (data or {}).get("assetPositions") or []:
        pos = row.get("position") or {}
        try:
            positions.append(
                {
                    "coin": pos.get("coin"),
                    "szi": str(pos.get("szi")),
                    "entry": pos.get("entryPx"),
                    "leverage": (pos.get("leverage") or {}).get("value"),
                    "upnl": pos.get("unrealizedPnl"),
                }
            )
        except AttributeError:
            continue
    equity = ((data or {}).get("marginSummary") or {}).get("accountValue")
    return IntelItem(
        id=_hid("hl", wallet, require_utc(now).strftime("%Y%m%d%H%M")),
        kind="hl_wallet",
        source_id=f"hl_wallet:{wallet}",
        known_at=require_utc(now),
        author_id=f"hl:{wallet}",
        text="",
        url=f"https://app.hyperliquid.xyz/explorer/address/{wallet}",
        extra={"positions": positions, "equity": equity},
    )


def hl_cohort_exposure(items: Sequence[IntelItem]) -> dict[str, dict[str, str]]:
    """Net signed size per coin across the cohort — the *change* of this is the signal
    candidate, never one wallet."""
    totals: dict[str, float] = {}
    for item in items:
        for pos in item.extra.get("positions") or []:
            try:
                totals[str(pos["coin"])] = totals.get(str(pos["coin"]), 0.0) + float(pos["szi"])
            except (KeyError, TypeError, ValueError):
                continue
    return {coin: {"net_size": f"{v:.6f}"} for coin, v in sorted(totals.items())}


# --- Bybit public metrics ------------------------------------------------------------------
BYBIT = "https://api.bybit.com"


def fetch_bybit_public(symbol: str, *, now: datetime, get: Getter = default_get) -> IntelItem:
    def _get(path: str, **params: Any) -> dict[str, Any]:
        query = urlencode({"category": "linear", "symbol": symbol, **params})
        raw = get(f"{BYBIT}{path}?{query}", {})
        data = json.loads(raw.decode())
        if data.get("retCode") not in (0, None):
            raise ValueError(f"bybit {path} retCode {data.get('retCode')}")
        return data.get("result") or {}

    ratio = (_get("/v5/market/account-ratio", period="5min", limit=1).get("list") or [{}])[0]
    oi = (_get("/v5/market/open-interest", intervalTime="5min", limit=1).get("list") or [{}])[0]
    funding = (_get("/v5/market/funding/history", limit=1).get("list") or [{}])[0]
    return IntelItem(
        id=_hid("bybit_public", symbol, require_utc(now).strftime("%Y%m%d%H%M")),
        kind="bybit_public",
        source_id=f"bybit_public:{symbol}",
        known_at=require_utc(now),
        author_id="bybit",
        text="",
        url=f"{BYBIT}/v5/market/account-ratio?category=linear&symbol={symbol}",
        extra={
            "buy_ratio": ratio.get("buyRatio"),
            "sell_ratio": ratio.get("sellRatio"),
            "open_interest": oi.get("openInterest"),
            "funding_rate": funding.get("fundingRate"),
            "funding_ts": funding.get("fundingRateTimestamp"),
        },
    )


# --- Fear & Greed ----------------------------------------------------------------------------
def fetch_fng(*, now: datetime, get: Getter = default_get) -> IntelItem:
    data = json.loads(get("https://api.alternative.me/fng/?limit=1&format=json", {}).decode())
    row = ((data or {}).get("data") or [{}])[0]
    return IntelItem(
        id=_hid("fng", str(row.get("timestamp") or require_utc(now).date())),
        kind="fng",
        source_id="fng:alternative.me",
        known_at=require_utc(now),
        author_id="alternative.me",
        text=str(row.get("value_classification") or ""),
        url="https://alternative.me/crypto/fear-and-greed-index/",
        extra={"value": row.get("value"), "classification": row.get("value_classification")},
    )
