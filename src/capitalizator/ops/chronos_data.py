"""Read-only Chronos surfaces. Empty vault stays empty. No invented prints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from capitalizator.authors.ingest import AuthorsIngest
from capitalizator.book.reconstruct import BookDirty
from capitalizator.card.live import CardLive, card_is_fresh
from capitalizator.desk.bars import TF_MINUTES, closed_bars_from_trades, forming_bar_from_trades
from capitalizator.desk.tape import _parse, event_from_jsonl_line
from capitalizator.exec.replay import ReplayEngine
from capitalizator.llm.daily_summary import DailySummary
from capitalizator.news_macro.from_intel import calendar_from_intel
from capitalizator.news_macro.ingest import NewsIngest, NewsRow, default_macro_path
from capitalizator.news_macro.merge import heartbeat_view, screen_events
from capitalizator.ops import i18n_ru
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.gates_from_sqlite import gates_from_sqlite
from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.vault import Vault, VaultError, iter_regular_files
from capitalizator.recorder.gap import SeqFault
from capitalizator.recorder.rows import rows_fast
from capitalizator.risk.session import MSK
from capitalizator.types import MarketEvent
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import MAP_VOTE_METHODS, ZoneEngine
from capitalizator.zones.model import Bar


def _symbol_stream_roots(tape: Path, *, symbol: str, stream: str) -> list[Path]:
    """Live layout is tape/bybit/SYMBOL/STREAM. Tests also drop parquet under tape/SYMBOL."""
    roots: list[Path] = []
    for candidate in (
        tape / "bybit" / symbol / stream,
        tape / symbol / stream,
        tape / symbol,
    ):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        roots.append(candidate)
    return roots


def _hour_key(path: Path) -> Path:
    if path.suffix == ".jsonl":
        return path.parent / path.stem
    return path.parent / path.name.split(".")[0]


def _hour_files_for(tf: str, limit: int) -> int:
    """Newest hour parts to open so `limit` closed bars can exist.

    One parquet/jsonl file is one hour. 96 files is four 1d candles — HTF
    buttons looked dead. Cap at 21 days so a click cannot walk the vault.
    """
    minutes = TF_MINUTES.get(tf, 15)
    need = (max(limit, 1) * minutes + 59) // 60 + 2
    return min(max(need, 24), 24 * 21)


def _load_symbol_stream(
    tape: Path, *, symbol: str, stream: str, max_files: int = 96
) -> list[MarketEvent]:
    """Read one symbol/stream, newest hour parts first. Jsonl wins its hour.

    Same rule as TapeCursor: the live feed is `hour=HH.jsonl`; parquet for that
    hour is skipped. Never the whole vault.
    """
    if tape.is_symlink() or not tape.is_dir() or not symbol or not stream:
        return []
    roots = _symbol_stream_roots(tape, symbol=symbol, stream=stream)
    if not roots:
        return []
    by_hour: dict[Path, list[Path]] = {}
    try:
        for root in roots:
            for path in iter_regular_files(root):
                if symbol not in path.parts:
                    continue
                if stream not in path.parts and root.name != symbol:
                    continue
                if path.suffix not in {".parquet", ".jsonl"}:
                    continue
                by_hour.setdefault(_hour_key(path), []).append(path)
    except VaultError:
        return []
    if not by_hour:
        return []

    def _mtime(key: Path) -> float:
        newest = 0.0
        for path in by_hour[key]:
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
        return newest

    hours = sorted(by_hour, key=_mtime, reverse=True)[:max_files]
    events: list[MarketEvent] = []
    for key in hours:
        files = by_hour[key]
        jsonl = [path for path in files if path.suffix == ".jsonl"]
        if jsonl:
            for path in jsonl:
                events.extend(_jsonl_events(path))
            continue
        for path in files:
            if path.suffix != ".parquet":
                continue
            try:
                table = pq.ParquetFile(path).read()
            except (OSError, ValueError):
                continue
            for row in rows_fast(table):
                event = _parse(row)
                if event is not None:
                    events.append(event)
    events.sort(key=lambda e: (e.exchange_ts, e.symbol, e.stream))
    return events


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
    # Never fall back to load_tape(): a live vault is gigabytes. Desk writes
    # last_price:* into sqlite; if those keys are missing the UI shows "—".
    return stored


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
    events = _load_symbol_stream(
        vault.tape, symbol=symbol, stream="trades", max_files=_hour_files_for(tf, limit)
    )
    bars = closed_bars_from_trades(events, symbol=symbol, tf=tf, now=when, already=set())
    rows = [_bar_row(bar) for bar in bars[-limit:]]
    forming = forming_bar_from_trades(events, symbol=symbol, tf=tf, now=when)
    if forming is not None:
        row = _bar_row(forming)
        row["forming"] = True
        rows.append(row)
    return rows


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
    events = _load_symbol_stream(vault.tape, symbol=symbol, stream="trades")
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
        event = event_from_jsonl_line(line)
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


def tape_tick(vault: Vault, *, symbol: str, tf: str = "15m") -> dict[str, Any]:
    """Book + last prints + forming bar. No 15-way dashboard refetch.

    Desk already flushes `book:{symbol}` every 0.5s. Lightweight Charts wants
    `series.update` on the open candle, not a parquet rebuild.
    """
    if tf not in TF_MINUTES:
        tf = "15m"
    minutes = TF_MINUTES[tf]
    hour_span = max(2, (minutes + 59) // 60 + 1)
    events = _load_symbol_stream(
        vault.tape, symbol=symbol, stream="trades", max_files=hour_span
    )
    when = datetime.now(tz=UTC)
    forming = forming_bar_from_trades(events, symbol=symbol, tf=tf, now=when)
    trades: list[dict[str, Any]] = []
    for event in events:
        if event.stream != "trades" or event.symbol != symbol:
            continue
        trades.append(
            {
                "symbol": event.symbol,
                "ts": event.exchange_ts.isoformat(),
                "px": str(event.payload.get("px") or ""),
                "qty": str(event.payload.get("qty") or ""),
                "side": str(event.payload.get("side") or ""),
            }
        )
    forming_row = None
    if forming is not None:
        forming_row = _bar_row(forming)
        forming_row["forming"] = True
    return {
        "symbol": symbol,
        "tf": tf,
        "book": book_for(vault, symbol=symbol),
        "last_price": last_prices(vault).get(symbol),
        "trades": trades[-30:],
        "forming": forming_row,
    }


def trades_for(vault: Vault, *, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    if limit < 1:
        limit = 1
    out: list[dict[str, Any]] = []
    # A handful of newest hours: the tape table is last prints, not a history scan.
    for event in _load_symbol_stream(vault.tape, symbol=symbol, stream="trades", max_files=4):
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


def _card_status(knowledge: Knowledge, *, symbol: str | None, now: datetime) -> str:
    """Same tokens as touch_screen. A bad card is a dash, not a 500."""
    target = (symbol or "").strip()
    if not target:
        return "no card"
    if not knowledge.available():
        return "no card"
    raw = knowledge.get_card_live(target)
    if raw is None:
        return "no card"
    try:
        card = CardLive.from_payload(raw)
    except (ValueError, KeyError, TypeError):
        return "no card"
    if not card_is_fresh(card, symbol=target, now=now):
        return "stale"
    return "fresh"


def news_payload(
    vault: Vault | None = None,
    *,
    now: datetime | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """CSV schedule + intel surprises + heartbeat. Missing heartbeat is stale."""
    when = now if now is not None else datetime.now(tz=UTC)
    csv: tuple[NewsRow, ...] = ()
    try:
        csv = tuple(NewsIngest.from_csv(default_macro_path()).rows)
    except FileNotFoundError:
        csv = ()
    intel: tuple[NewsRow, ...] = ()
    heartbeat_raw: str | None = None
    card_status = "no card"
    if vault is not None:
        knowledge = open_knowledge(vault, create=False)
        try:
            if knowledge.available():
                intel = calendar_from_intel(knowledge, now=when)
                heartbeat_raw = knowledge.meta("intel_heartbeat")
                card_status = _card_status(knowledge, symbol=symbol, now=when)
        finally:
            knowledge.close()
    view = heartbeat_view(heartbeat_raw, now=when)
    warn = card_status if card_status in {"no card", "stale"} else None
    return {
        "events": screen_events(csv=csv, intel=intel, now=when),
        "card_status": card_status,
        "card_status_label": i18n_ru.ru(warn) if warn else None,
        "intel_stale_label": i18n_ru.ru("intel:stale") if view["stale"] else None,
        **view,
    }


def news_rows() -> list[dict[str, Any]]:
    """CSV-only list for callers without a vault."""
    return list(news_payload()["events"])


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
