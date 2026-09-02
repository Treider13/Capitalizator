"""Read-only Chronos surfaces. Empty vault stays empty. No invented prints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from capitalizator.authors.ingest import AuthorsIngest
from capitalizator.authors.sources import default_sources_path, load_sources
from capitalizator.desk.bars import TF_MINUTES, closed_bars_from_trades
from capitalizator.desk.tape import load_tape
from capitalizator.llm.daily_summary import DailySummary
from capitalizator.news_macro.ingest import NewsIngest, default_macro_path
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.gates_from_sqlite import gates_from_sqlite
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import Vault
from capitalizator.risk.session import MSK, load_time_config
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import MAP_VOTE_METHODS, ZoneEngine
from capitalizator.zones.model import Bar


def _safe(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload)
    if contains_advice(text):
        raise ValueError("chronos payload must not advise")
    return payload


def session_window() -> dict[str, Any]:
    cfg = load_time_config()
    return {
        "tz": str(cfg["session_tz"]),
        "start": str(cfg["session_start"]),
        "end": str(cfg["session_end"]),
    }


def last_prices(vault: Vault) -> dict[str, str]:
    knowledge = open_knowledge(vault, create=False)
    try:
        stored = knowledge.last_prices() if knowledge.available() else {}
    finally:
        knowledge.close()
    if stored:
        return stored
    out: dict[str, str] = {}
    for event in load_tape(vault.tape):
        if event.stream != "trades":
            continue
        px = event.payload.get("px")
        if px is None:
            continue
        out[event.symbol] = str(px)
    return out


def last_jury(vault: Vault) -> dict[str, dict[str, Any]]:
    knowledge = open_knowledge(vault, create=False)
    try:
        rows = knowledge.journal_rows() if knowledge.available() else []
    finally:
        knowledge.close()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        prev = latest.get(symbol)
        if prev is None or str(row.get("touch_ts") or "") >= str(prev.get("touch_ts") or ""):
            latest[symbol] = {
                "symbol": symbol,
                "jury": row.get("jury"),
                "cav_label": row.get("cav_label"),
                "zlg_label": row.get("zlg_label"),
                "touch_ts": row.get("touch_ts"),
                "touch_id": row.get("touch_id"),
            }
    return latest


def session_counts(vault: Vault, *, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(tz=UTC)
    local = when.astimezone(MSK)
    day = local.date().isoformat()
    knowledge = open_knowledge(vault, create=False)
    try:
        rows = knowledge.journal_rows() if knowledge.available() else []
    finally:
        knowledge.close()
    n_touches = 0
    n_shadow = 0
    n_skip = 0
    n_no_tvh = 0
    for row in rows:
        ts = str(row.get("touch_ts") or "")
        if not ts.startswith(day):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if parsed.astimezone(MSK).date().isoformat() != day:
                    continue
            except ValueError:
                continue
        n_touches += 1
        if row.get("shadow_would"):
            n_shadow += 1
        if row.get("skip_reason"):
            n_skip += 1
        if row.get("skip_reason") == "no_tvh":
            n_no_tvh += 1
    return {
        "n_touches": n_touches,
        "n_shadow": n_shadow,
        "n_skip": n_skip,
        "n_no_tvh": n_no_tvh,
    }


def latest_touch(vault: Vault, *, symbol: str | None = None) -> dict[str, Any] | None:
    knowledge = open_knowledge(vault, create=False)
    try:
        rows = knowledge.journal_rows() if knowledge.available() else []
        claims = knowledge.list_claims() if knowledge.available() else []
    finally:
        knowledge.close()
    picked: dict[str, Any] | None = None
    for row in rows:
        if symbol and str(row.get("symbol") or "") != symbol:
            continue
        if picked is None or str(row.get("touch_ts") or "") >= str(picked.get("touch_ts") or ""):
            picked = row
    if picked is None:
        return None
    card_id = picked.get("card_id")
    picked = dict(picked)
    picked["claims"] = [c for c in claims if str(c.get("card_id") or "") == str(card_id or "")]
    return picked


def bars_for(
    vault: Vault,
    *,
    symbol: str,
    tf: str = "15m",
    limit: int = 200,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if tf not in TF_MINUTES:
        raise ValueError(f"unsupported tf: {tf!r}")
    if limit < 1:
        limit = 1
    when = now or datetime.now(tz=UTC)
    events = [e for e in load_tape(vault.tape) if e.symbol == symbol and e.stream == "trades"]
    bars = closed_bars_from_trades(events, symbol=symbol, tf=tf, now=when, already=set())
    return [_bar_row(bar) for bar in bars[-limit:]]


def _bar_row(bar: Bar) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "tf": bar.tf,
        "open_ts": bar.open_ts.isoformat(),
        "close_ts": bar.close_ts.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": None if bar.volume is None else str(bar.volume),
    }


def zones_for(vault: Vault, *, symbol: str, now: datetime | None = None) -> list[dict[str, Any]]:
    knowledge = open_knowledge(vault, create=False)
    try:
        stored = knowledge.list_zones(symbol=symbol) if knowledge.available() else []
    finally:
        knowledge.close()
    vote = load_registry().working_tf

    def _stale_map(row: dict[str, Any]) -> bool:
        return (
            str(row.get("method") or "") in MAP_VOTE_METHODS
            and str(row.get("tf") or "") != vote
        )

    kept = [row for row in stored if not _stale_map(row)]
    had_stale = len(kept) < len(stored)
    if stored and not had_stale:
        return stored
    when = now or datetime.now(tz=UTC)
    events = [e for e in load_tape(vault.tape) if e.symbol == symbol and e.stream == "trades"]
    raw_bars = closed_bars_from_trades(
        events, symbol=symbol, tf=vote, now=when, already=set()
    )
    built = ZoneEngine(tick_size=Decimal("0.1")).build(symbol, when, raw_bars)
    rebuilt = [
        {
            "zone_id": z.zone_id,
            "symbol": z.symbol,
            "tf": z.tf,
            "side": z.side,
            "lo": str(z.lo),
            "hi": str(z.hi),
            "method": z.method,
            "created_as_of": z.created_as_of.isoformat(),
        }
        for z in built
    ]
    if not had_stale:
        return rebuilt
    merged = {str(row["zone_id"]): row for row in rebuilt}
    for row in kept:
        zid = str(row.get("zone_id") or "")
        if zid:
            merged[zid] = row
    return list(merged.values())


def book_for(vault: Vault, *, symbol: str) -> dict[str, Any]:
    knowledge = open_knowledge(vault, create=False)
    try:
        stored = knowledge.book_levels(symbol) if knowledge.available() else None
    finally:
        knowledge.close()
    if stored is not None:
        return stored
    return {"symbol": symbol, "bids": [], "asks": [], "ts": None}


def trades_for(vault: Vault, *, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    if limit < 1:
        limit = 1
    out: list[dict[str, Any]] = []
    for event in load_tape(vault.tape):
        if event.stream != "trades" or event.symbol != symbol:
            continue
        out.append(
            {
                "symbol": event.symbol,
                "ts": event.exchange_ts.isoformat(),
                "px": str(event.payload.get("px") or ""),
                "qty": str(event.payload.get("qty") or ""),
                "side": str(event.payload.get("side") or ""),
            }
        )
    return out[-limit:]


def news_rows() -> list[dict[str, Any]]:
    try:
        ingest = NewsIngest.from_csv(default_macro_path())
    except FileNotFoundError:
        return []
    return [
        {
            "event_id": row.event_id,
            "class": row.event_class,
            "event_time": row.event_time.isoformat(),
            "known_at": row.known_at.isoformat(),
            "assets": list(row.assets),
            "source": row.source,
            "notes": row.notes,
        }
        for row in ingest.rows
    ]


def author_sources() -> list[dict[str, Any]]:
    try:
        book = load_sources(default_sources_path())
    except FileNotFoundError:
        return []
    return [
        {"id": src.source_id, "kind": src.kind, "url": src.url}
        for src in book.sources
    ]


def author_rows(vault: Vault) -> list[dict[str, Any]]:
    path = vault.root / "authors.jsonl"
    if not path.is_file():
        return []
    rows = AuthorsIngest.from_jsonl(path).rows
    return [
        {
            "author_id": row.author_id,
            "ts": row.ts.isoformat(),
            "source": row.source,
            "text": row.text,
            "known_at": row.known_at.isoformat(),
        }
        for row in rows
        if row.source.lower() not in {"telegram", "tg", "tip"}
    ]


def llm_summary(vault: Vault) -> dict[str, Any]:
    knowledge = open_knowledge(vault, create=False)
    try:
        latest = knowledge.latest_report() if knowledge.available() else None
    finally:
        knowledge.close()
    if latest is None or not str(latest.get("body") or "").strip():
        return {"summary": "нет данных", "trade_advice": False}
    return DailySummary().run(str(latest["body"]))


def dashboard(vault: Vault) -> dict[str, Any]:
    knowledge = open_knowledge(vault, create=False)
    try:
        gates = gates_from_sqlite(knowledge)
        taps_risk = {
            "max_lev": None,
            "target_risk": None,
        }
    finally:
        knowledge.close()
    from capitalizator.ops.phase import load_phase

    phase = load_phase()
    taps_risk = {
        "max_lev": int(phase["max_lev"]),
        "target_risk": float(phase["target_risk"]),
    }
    counts = session_counts(vault)
    latest = latest_touch(vault)
    return _safe(
        {
            "session": session_window(),
            "today": counts,
            "last_touch": latest,
            "risk": taps_risk,
            "gates": gates,
            "last_price": last_prices(vault),
            "last_jury": last_jury(vault),
        }
    )


def hello_status(vault: Vault) -> dict[str, Any]:
    from capitalizator.ops.product import hello_recorded

    return {"hello_ok": hello_recorded(vault), "real": False}
