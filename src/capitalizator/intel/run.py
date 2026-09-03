"""intel-fetcher: one cycle every N minutes. Contour B's raw material, honestly clocked.

  sources (Settings/console) → fetch → intel_item (dedup by id, known_at = now)
  text items → LLM extraction (if a provider is configured) → author_call rows
  author calls past their horizon → resolved against OUR last prices (authors.resolve)
  author weights (authors.score: shrinkage, n≥5) → meta `author_weights`
  bybit_public / fng / hl cohort → meta for the desk and the console
  each source: last_ok / last_error on the source row (visible in Настройки)

What this never does: place orders, change size, read exchange keys, read Telegram.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from capitalizator.authors.ingest import AuthorCall
from capitalizator.authors.resolve import AuthorsResolve, ResolveRule
from capitalizator.authors.score import weight as author_weight
from capitalizator.intel import fetchers
from capitalizator.intel.llm import BudgetExceeded, LLMClient
from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.settings import (
    Settings,
    ensure_default_sources,
    load_sources,
    update_source_health,
)
from capitalizator.ops.vault import Vault, init_vault, load_vault
from capitalizator.screener.universe import default_week0_path, load_universe
from capitalizator.types import require_utc

TEXT_KINDS = {"rss", "reddit", "x_account"}
RESOLVE_THRESHOLD_PCT = Decimal("0.01")  # 2.12.2: ±1% over the horizon = hit


def _llm(settings: Settings, knowledge: Knowledge) -> LLMClient | None:
    provider = settings.get("llm.provider") or "none"
    if provider == "none":
        return None
    key = settings.get("llm.api_key")
    model = settings.get("llm.model")
    if not key or not model:
        return None
    budget = float(settings.get("llm.monthly_budget_usd") or "0")
    if budget <= 0:
        return None
    return LLMClient(
        provider=provider, model=model, api_key=key, monthly_budget_usd=budget, knowledge=knowledge
    )


def fetch_sources(
    knowledge: Knowledge,
    settings: Settings,
    *,
    now: datetime,
    get: fetchers.Getter = fetchers.default_get,
    post: fetchers.Poster = fetchers.default_post,
) -> dict[str, Any]:
    rows = load_sources(knowledge)
    health: dict[str, tuple[str | None, str | None]] = {}
    stored = 0
    hl_items: list[fetchers.IntelItem] = []
    reddit_token: str | None = None
    cid, csec = settings.get("reddit.client_id"), settings.get("reddit.client_secret")
    if cid and csec and any(r.get("kind") == "reddit" and r.get("enabled") for r in rows):
        try:
            reddit_token = fetchers.reddit_token(cid, csec, post=post)
        except Exception as exc:
            knowledge.set_meta("reddit_auth_error", type(exc).__name__)
    for row in rows:
        if not row.get("enabled"):
            continue
        kind, value = str(row.get("kind")), str(row.get("value"))
        try:
            if kind == "rss":
                items = fetchers.fetch_rss(value, now=now, get=get)
            elif kind == "reddit":
                items = fetchers.fetch_reddit(value, now=now, get=get, token=reddit_token)
            elif kind == "x_account":
                items = fetchers.fetch_x_account(
                    value, bearer=settings.get("x.bearer") or "", now=now, get=get
                )
            elif kind == "hl_wallet":
                item = fetchers.fetch_hl_wallet(value, now=now, post=post)
                hl_items.append(item)
                items = [item]
            else:  # tradingview_own: export-based, handled by the operator's own upload
                items = []
            for item in items:
                if knowledge.put_intel_item(
                    item.id,
                    kind=item.kind,
                    source_id=item.source_id,
                    known_at=item.known_at.isoformat(),
                    payload=item.payload(),
                ):
                    stored += 1
            health[str(row.get("id"))] = (now.isoformat(), None)
        except Exception as exc:  # one dead source must not stop the others
            # type + status only: an HTTPError text may carry a URL with credentials
            code = getattr(exc, "code", None) or getattr(exc, "status", None)
            health[str(row.get("id"))] = (
                row.get("last_ok"), f"{type(exc).__name__}" + (f" {code}" if code else "")
            )
    update_source_health(knowledge, health)
    if hl_items:
        knowledge.set_meta(
            "hl_cohort",
            json.dumps(
                {
                    "at": now.isoformat(),
                    "n_wallets": len(hl_items),
                    "exposure": fetchers.hl_cohort_exposure(hl_items),
                },
                sort_keys=True,
            ),
        )
    return {"sources": len(rows), "stored": stored}


def fetch_market_metrics(
    knowledge: Knowledge, *, now: datetime, get: fetchers.Getter = fetchers.default_get
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    symbols = list(load_universe(default_week0_path()).symbols)
    for symbol in symbols:
        try:
            item = fetchers.fetch_bybit_public(symbol, now=now, get=get)
            knowledge.put_intel_item(
                item.id, kind=item.kind, source_id=item.source_id,
                known_at=item.known_at.isoformat(), payload=item.payload(),
            )
            knowledge.set_meta(
                f"bybit_public:{symbol}",
                json.dumps({"at": now.isoformat(), **item.extra}, default=str),
            )
            out[symbol] = "ok"
        except Exception as exc:
            out[symbol] = f"{type(exc).__name__}: {exc}"[:200]
    try:
        fng = fetchers.fetch_fng(now=now, get=get)
        knowledge.put_intel_item(
            fng.id, kind=fng.kind, source_id=fng.source_id,
            known_at=fng.known_at.isoformat(), payload=fng.payload(),
        )
        knowledge.set_meta(
            "sentiment", json.dumps({"at": now.isoformat(), **fng.extra}, default=str)
        )
        out["fng"] = "ok"
    except Exception as exc:
        out["fng"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def extract_claims(
    knowledge: Knowledge,
    llm: LLMClient | None,
    *,
    now: datetime,
    since_h: int = 6,
    max_items: int = 60,
) -> dict[str, Any]:
    """Text items without an extraction → LLM → author_call rows (claims + horizon required)."""
    if llm is None:
        return {"skipped": "no llm configured"}
    since = (now - timedelta(hours=since_h)).isoformat()
    done = {c.get("item_id") for c in knowledge.author_calls()}
    n_calls = n_items = 0
    for item in knowledge.intel_items(since=since, limit=1000):
        if item["kind"] not in TEXT_KINDS or item["id"] in done or not item.get("text"):
            continue
        if n_items >= max_items:
            break
        n_items += 1
        try:
            ext = llm.extract(str(item["text"]))
        except BudgetExceeded as exc:
            knowledge.set_meta(
                "llm_budget_stop", json.dumps({"at": now.isoformat(), "why": str(exc)})
            )
            break
        except Exception as exc:
            knowledge.set_meta("llm_last_error", type(exc).__name__)
            continue
        payload_base = {
            "item_id": item["id"],
            "author_id": item.get("author_id"),
            "source": item["kind"],
            "ts": item.get("published_at") or item["known_at"],
            "known_at": now.isoformat(),
            "text": str(item["text"])[:1000],
            "extraction": None if ext is None else ext.payload(),
        }
        usable = [] if ext is None else [
            c for c in ext.claims if c.side != "none" and c.horizon is not None
        ]
        if not usable:
            # recorded as parsed-without-a-call, so the item is not re-sent every cycle
            knowledge.put_author_call(
                f"{item['id']}:none", {**payload_base, "claims": [], "horizon": None}
            )
            continue
        assert ext is not None
        for i, claim in enumerate(usable):
            knowledge.put_author_call(
                f"{item['id']}:{i}",
                {
                    **payload_base,
                    "call_id": f"{item['id']}:{i}",
                    "claims": [f"{claim.asset}:{claim.side}"],
                    "asset": claim.asset,
                    "side": claim.side,
                    "horizon": claim.horizon,
                    "target": claim.target,
                    "confidence": claim.confidence,
                    "promo": ext.promo or ext.ref_link,
                    "hit": None,
                    "resolved_ts": None,
                },
            )
            n_calls += 1
    return {"items": n_items, "calls": n_calls, "spent_usd": round(llm.spent(), 4)}


def resolve_calls(knowledge: Knowledge, *, now: datetime) -> dict[str, Any]:
    """Calls past their horizon are scored against OUR last prices (2.12.2)."""
    prices = {k: Decimal(str(v)) for k, v in knowledge.last_prices().items()}
    resolver = AuthorsResolve()
    resolved = 0
    for row in knowledge.author_calls():
        if row.get("hit") is not None or not row.get("horizon") or not row.get("asset"):
            continue
        px_now = prices.get(str(row["asset"]))
        ref = row.get("ref_px")
        if px_now is None:
            continue
        if ref is None:
            # first sighting: the reference is our price now, and the horizon starts NOW
            # (a post found after its horizon would otherwise resolve at once with move≈0
            # and punish slow sources — audit B10)
            row["ref_px"] = str(px_now)
            row["ref_ts"] = now.isoformat()
            knowledge.put_author_call(_call_id(row), row)
            continue
        call = AuthorCall(
            author_id=str(row["author_id"]),
            ts=datetime.fromisoformat(str(row.get("ref_ts") or row["ts"]).replace("Z", "+00:00")),
            source=str(row["source"]),
            text=str(row.get("text") or ""),
            known_at=datetime.fromisoformat(str(row["known_at"])),
            claims=tuple(row.get("claims") or ()),
            horizon=str(row["horizon"]),
        )
        rule = ResolveRule(
            direction="up" if row["side"] == "long" else "down",
            threshold_pct=RESOLVE_THRESHOLD_PCT,
        )
        closed = resolver.close(call, now=now, ref_px=Decimal(str(ref)), close_px=px_now, rule=rule)
        if closed.hit is not None:
            row["hit"] = closed.hit
            row["resolved_ts"] = closed.resolved_ts.isoformat() if closed.resolved_ts else None
            row["close_px"] = str(px_now)
            knowledge.put_author_call(_call_id(row), row)
            resolved += 1
    return {"resolved": resolved}


def _call_id(row: dict[str, Any]) -> str:
    return str(row.get("call_id") or f"{row['item_id']}:{row.get('side')}:{row.get('asset')}")


def author_weights(knowledge: Knowledge, *, now: datetime) -> dict[str, Any]:
    stats: dict[str, list[int]] = {}
    for row in knowledge.author_calls():
        if row.get("hit") is None:
            continue
        aid = str(row.get("author_id"))
        hits, n = stats.setdefault(aid, [0, 0])
        stats[aid] = [hits + int(bool(row["hit"])), n + 1]
    weights = {
        aid: {"hits": h, "n": n, "weight": str(author_weight(h, n))}
        for aid, (h, n) in stats.items()
    }
    knowledge.set_meta(
        "author_weights", json.dumps({"at": now.isoformat(), "authors": weights}, sort_keys=True)
    )
    return {"authors": len(weights)}


def cycle(
    vault: Vault,
    knowledge: Knowledge,
    *,
    now: datetime | None = None,
    get: fetchers.Getter = fetchers.default_get,
    post: fetchers.Poster = fetchers.default_post,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    when = require_utc(now or datetime.now(tz=UTC))
    # this process has the internet; it must never hold exchange keys in memory
    settings = Settings(vault, exclude_prefixes=("bybit.",))
    ensure_default_sources(knowledge)
    out = {"at": when.isoformat()}
    out["fetch"] = fetch_sources(knowledge, settings, now=when, get=get, post=post)
    out["market"] = fetch_market_metrics(knowledge, now=when, get=get)
    client = llm if llm is not None else _llm(settings, knowledge)
    out["extract"] = extract_claims(knowledge, client, now=when)
    out["resolve"] = resolve_calls(knowledge, now=when)
    out["weights"] = author_weights(knowledge, now=when)
    knowledge.set_meta("intel_status", json.dumps(out, default=str, sort_keys=True))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="intel-fetcher: sources → knowledge. No keys of the exchange."
    )
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--every-s", type=int, default=300)
    args = parser.parse_args(argv)
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    knowledge = open_knowledge(vault)
    try:
        if not args.serve:
            print(json.dumps(cycle(vault, knowledge), ensure_ascii=False, default=str))
            return 0
        print(json.dumps({"process": "intel", "every_s": args.every_s, "serve": True}), flush=True)
        while True:
            started = time.monotonic()
            try:
                cycle(vault, knowledge)
                knowledge.set_meta("intel_error", "")
            except Exception as exc:  # keep the loop alive; the console shows intel_status
                knowledge.set_meta("intel_error", type(exc).__name__)
            # the compose healthcheck reads this: a hung cycle is a sick container
            knowledge.set_meta("intel_heartbeat", datetime.now(tz=UTC).isoformat())
            time.sleep(max(5.0, args.every_s - (time.monotonic() - started)))
    finally:
        knowledge.close()


if __name__ == "__main__":
    raise SystemExit(main())
