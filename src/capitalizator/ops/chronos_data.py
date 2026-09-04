"""Read-only Chronos surfaces. Empty vault stays empty. No invented prints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from capitalizator.authors.ingest import AuthorsIngest
from capitalizator.book.reconstruct import BookDirty
from capitalizator.desk.bars import TF_MINUTES, closed_bars_from_trades
from capitalizator.desk.tape import _parse, load_tape
from capitalizator.exec.replay import ReplayEngine
from capitalizator.llm.daily_summary import DailySummary
from capitalizator.news_macro.ingest import NewsIngest, default_macro_path
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.gates_from_sqlite import gates_from_sqlite
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import Vault, VaultError, iter_regular_files
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rows import rows_fast
from capitalizator.risk.session import MSK
from capitalizator.types import MarketEvent
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import MAP_VOTE_METHODS, ZoneEngine
from capitalizator.zones.model import Bar


def _safe(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload)
    if contains_advice(text):
        raise ValueError("chronos payload must not advise")
    return payload


def session_window(now: datetime | None = None) -> dict[str, Any]:
    """The SessionPolicy window that holds `now` (one calendar for the whole desk; the
    old time.yaml Moscow window next to it was a second, contradicting clock)."""
    from capitalizator.risk.sessions import SessionPolicy

    policy = SessionPolicy.load()
    when = now or datetime.now(tz=UTC)
    state = policy.window(when)
    win = next((w for w in (*policy.windows, policy.weekend) if w.name == state.name), None)
    start = end = None
    if win is not None and win.name != "weekend":
        start = win.start.isoformat(timespec="minutes")
        end = "24:00" if win.end_is_midnight else win.end.isoformat(timespec="minutes")
    return {
        "tz": "UTC",
        "name": state.name,
        "start": start,
        "end": end,
        "weekend": state.weekend,
        "closed": win is None or not win.ideas or win.budget <= 0 or win.size_mult <= 0,
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
    cfg = load_registry()
    vote = cfg.working_tf

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
    raw_bars: list[Bar] = []
    for tf in cfg.structure_tfs:
        raw_bars.extend(
            closed_bars_from_trades(events, symbol=symbol, tf=tf, now=when, already=set())
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


def _jsonl_events(path: Path) -> list[MarketEvent]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[MarketEvent] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            row["exchange_ts"] = datetime.fromisoformat(str(row["exchange_ts"]))
            row["recv_ts"] = datetime.fromisoformat(str(row["recv_ts"]))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        event = _parse(row)
        if event is not None:
            out.append(event)
    return out


def _replay_tape_events(tape: Path) -> list[MarketEvent]:
    """Parquet archive plus live hour=HH.jsonl. Jsonl wins for its hour — same as TapeCursor.

    `load_tape` stays parquet-only (bars / last price). Replay must see the live feed.
    """
    if tape.is_symlink() or not tape.is_dir():
        return []
    try:
        paths = list(iter_regular_files(tape))
    except VaultError:
        return []
    live_hours = {path.parent / path.stem for path in paths if path.suffix == ".jsonl"}
    events: list[MarketEvent] = []
    for path in paths:
        if path.suffix == ".jsonl":
            events.extend(_jsonl_events(path))
            continue
        if path.suffix != ".parquet":
            continue
        hour_key = path.parent / path.name.split(".")[0]
        if hour_key in live_hours:
            continue
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, ValueError):
            continue
        for row in rows_fast(table):
            event = _parse(row)
            if event is not None:
                events.append(event)
    return events


def _book_order(event: MarketEvent) -> tuple[datetime, int, int]:
    seq = event.seq if event.seq is not None else -1
    kind = 0 if event.stream == "snapshot" else 1
    return (event.exchange_ts, seq, kind)


def replay_for(vault: Vault, *, symbol: str) -> dict[str, Any]:
    """Replay recorded snapshot+diff for one symbol. Empty tape is empty, not invented."""
    events = [
        e
        for e in _replay_tape_events(vault.tape)
        if e.symbol == symbol and e.stream in {"snapshot", "book_diff"}
    ]
    events.sort(key=_book_order)
    if not events:
        return {
            "symbol": symbol,
            "n": 0,
            "ok": True,
            "last_bid": None,
            "last_ask": None,
            "last_seq": None,
        }
    try:
        cps = ReplayEngine().run_events(events)
    except (BookDirty, SeqFault, ValueError) as exc:
        return {
            "symbol": symbol,
            "n": 0,
            "ok": False,
            "reason": str(exc),
            "last_bid": None,
            "last_ask": None,
            "last_seq": None,
        }
    last = cps[-1] if cps else None
    return {
        "symbol": symbol,
        "n": len(cps),
        "ok": True,
        "last_bid": None if last is None or last.best_bid is None else str(last.best_bid),
        "last_ask": None if last is None or last.best_ask is None else str(last.best_ask),
        "last_seq": None if last is None else last.seq,
    }


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


def author_sources(vault: Vault) -> list[dict[str, Any]]:
    """The ONE source registry (SQLite `intel_sources`, edited in Настройки). The old
    `infra/authors/sources.yaml` next to it was a second list with its own vocabulary."""
    from capitalizator.ops.settings import load_sources as load_intel_sources

    knowledge = open_knowledge(vault, create=False)
    try:
        rows = load_intel_sources(knowledge)
    finally:
        knowledge.close()
    return [
        {
            "id": r.get("id"),
            "kind": r.get("kind"),
            "url": r.get("value"),
            "enabled": bool(r.get("enabled")),
            "last_ok": r.get("last_ok"),
            "last_error": r.get("last_error"),
        }
        for r in rows
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
    from capitalizator.ops.phase import load_phase
    from capitalizator.risk.config import load_risk_config

    knowledge = open_knowledge(vault, create=False)
    try:
        gates = gates_from_sqlite(knowledge)
        cfg = load_risk_config(knowledge)
    finally:
        knowledge.close()
    phase = load_phase()
    # the operator's risk menu (what the desk sizes with) next to the phase ceilings
    # it may not exceed — the dashboard used to show only the ceiling as "риск"
    taps_risk = {
        "max_lev": str(cfg.max_lev),
        "target_risk": str(cfg.target_risk_pct),
        "ceiling_max_lev": int(phase["max_lev"]),
        "ceiling_target_risk": float(phase["target_risk"]),
        "deposit_share_per_trade": str(cfg.deposit_share_per_trade),
        "max_stop_pct": str(cfg.max_stop_pct),
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
    """Flag plus whether the last hello actually talked to the venue. GET does not ping."""
    import json

    from capitalizator.ops.handoff import experience_snapshot
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.product import cred_present, hello_recorded

    hello_ok = hello_recorded(vault)
    result: dict[str, Any] | None = None
    knowledge = open_knowledge(vault, create=False)
    try:
        raw = knowledge.meta("hello_result") if knowledge.available() else None
        if raw:
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                result = {"ok": bool(loaded.get("ok"))}
        experience = experience_snapshot(knowledge)
    finally:
        knowledge.close()
    return {
        "hello_ok": hello_ok,
        "real": bool(result and result.get("ok")),
        "cred_present": cred_present(vault),
        "experience": experience,
    }
