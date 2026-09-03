"""Console read-models for money, positions, queues and honesty banners (D-32…D-37).

Everything here is read from SQLite meta/tables the desk, signer and recorder
already write. Missing data is reported as missing with an age — never as zero.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from capitalizator.ops.knowledge import Knowledge
from capitalizator.risk.config import load_risk_config

STALE_DESK_S = 5.0
STALE_RECORDER_S = 10.0
STALE_EXCHANGE_S = 120.0


def _age(raw: str | None, now: datetime) -> float | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (now - ts).total_seconds()


def _json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        got = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return got if isinstance(got, dict) else None


def paper_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Filled, closed paper trades only; unfilled counted separately (never 0 R)."""
    filled = [r for r in rows if r.get("entry_px") not in (None, "")]
    rs: list[Decimal] = []
    for r in filled:
        raw = r.get("r_net")
        if raw not in (None, ""):
            rs.append(Decimal(str(raw)))
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins, Decimal("0"))
    gross_loss = -sum(losses, Decimal("0"))
    n = len(rs)
    winrate = None if n == 0 else Decimal(len(wins)) / Decimal(n)
    ci = None
    if n:
        # Wilson 95% interval — how sure we are about the winrate at this n
        z = Decimal("1.96")
        p = winrate or Decimal("0")
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** Decimal("0.5")) / denom
        ci = [str(max(Decimal("0"), centre - half)), str(min(Decimal("1"), centre + half))]
    return {
        "n": n,
        "n_unfilled": len(rows) - len(filled),
        "winrate": None if winrate is None else str(winrate),
        "winrate_ci95": ci,
        "avg_r_net": None if n == 0 else str(sum(rs, Decimal("0")) / n),
        "sum_r_net": None if n == 0 else str(sum(rs, Decimal("0"))),
        "profit_factor": None if gross_loss == 0 else str(gross_win / gross_loss),
        "pnl_net": str(
            sum(
                (
                    Decimal(str(r.get("realized") or 0))
                    - Decimal(str(r.get("fees") or 0))
                    - Decimal(str(r.get("funding") or 0))
                    for r in filled
                ),
                Decimal("0"),
            )
        ),
        "fees": str(sum((Decimal(str(r.get("fees") or 0)) for r in filled), Decimal("0"))),
        "funding": str(sum((Decimal(str(r.get("funding") or 0)) for r in filled), Decimal("0"))),
        "exit_reasons": _count(filled, "exit_reason"),
        "mae_r_p90": _quantile([Decimal(str(r["mae_r"])) for r in filled if r.get("mae_r")], 0.9),
    }


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "—")
        out[k] = out.get(k, 0) + 1
    return out


def _quantile(values: list[Decimal], q: float) -> str | None:
    if not values:
        return None
    xs = sorted(values)
    idx = min(len(xs) - 1, int(round(q * (len(xs) - 1))))
    return str(xs[idx])


def account_view(knowledge: Knowledge, *, now: datetime | None = None) -> dict[str, Any]:
    when = now or datetime.now(tz=UTC)
    account = _json(knowledge.meta("account")) if knowledge.available() else None
    exchange = _json(knowledge.meta("exchange_state")) if knowledge.available() else None
    recorder = _json(knowledge.meta("recorder_status")) if knowledge.available() else None
    hello = _json(knowledge.meta("hello_result")) if knowledge.available() else None
    blocked_raw = knowledge.meta("entries_blocked") if knowledge.available() else None
    try:
        blocked = json.loads(blocked_raw) if blocked_raw else []
    except json.JSONDecodeError:
        blocked = []
    refused = _json(knowledge.meta("refused_symbols")) if knowledge.available() else None
    desk_age = _age(knowledge.meta("desk_heartbeat") if knowledge.available() else None, when)
    rec_age = _age(recorder.get("at") if recorder else None, when)
    exch_age = _age(exchange.get("at") if exchange else None, when)
    paper_all = knowledge.paper_trades() if knowledge.available() else []
    day = when.date().isoformat()
    paper_today = [r for r in paper_all if str(r.get("closed_at") or "").startswith(day)]
    by_source = {
        src: paper_stats([r for r in paper_all if r.get("source") == src])
        for src in ("shadow", "fade", "demo")
    }
    cfg = load_risk_config(knowledge)
    banners: list[str] = []
    if desk_age is None:
        banners.append("ДЕСК: нет сердцебиения — данных о столе нет")
    elif desk_age > STALE_DESK_S:
        banners.append(f"ДЕСК молчит {desk_age:.0f} с")
    if recorder is None:
        banners.append("РЕКОРДЕР: статуса нет — живой ленты нет")
    elif rec_age is not None and rec_age > STALE_RECORDER_S:
        banners.append(f"РЕКОРДЕР молчит {rec_age:.0f} с")
    else:
        for name, st in (recorder or {}).get("streams", {}).items():
            age = st.get("last_age_s")
            if age is None:
                banners.append(f"РЕКОРДЕР: поток {name} ещё не пришёл")
            elif age > STALE_RECORDER_S:
                banners.append(f"РЕКОРДЕР: поток {name} молчит {age:.0f} с")
    if exchange is None:
        banners.append("БИРЖА: состояния нет — эквити/позиции не читались (нет ключа или gateway)")
    else:
        if exch_age is not None and exch_age > STALE_EXCHANGE_S:
            banners.append(f"БИРЖА: состояние устарело на {exch_age:.0f} с")
        if exchange.get("equity_error"):
            banners.append(f"БИРЖА: эквити не прочитано: {exchange['equity_error']}")
        if exchange.get("mismatches"):
            n_mm = len(exchange["mismatches"])
            banners.append(f"СВЕРКА: {n_mm} расхождений — входы заблокированы")
        if exchange.get("stop_missing"):
            banners.append("СТОП НЕ ПОДТВЕРЖДЁН биржей: " + ", ".join(exchange["stop_missing"]))
    if account is None:
        banners.append("СЧЁТ: снимка нет")
    else:
        if account.get("equity_source") == "paper":
            banners.append("ЭКВИТИ бумажное (paper_equity из настроек), не с биржи")
        if account.get("halted"):
            banners.append(f"КРАН закрыт: {account.get('halt_reason')} — новых входов нет")
    if blocked:
        banners.append("ВХОДЫ ЗАБЛОКИРОВАНЫ: " + ", ".join(blocked))
    if refused:
        banners.append("ИНСТРУМЕНТЫ без фактов (не торгуются): " + ", ".join(sorted(refused)))
    if hello is None:
        banners.append("КОМИССИЯ — предположение VIP0; hello с биржей не выполнялся")
    return {
        "at": when.isoformat(),
        "account": account,
        "exchange": exchange,
        "recorder": recorder,
        "recorder_age_s": rec_age,
        "desk_heartbeat_age_s": desk_age,
        "entries_blocked": blocked,
        "refused_symbols": refused or {},
        "risk_config": cfg.to_payload(),
        "paper": {
            "today": paper_stats(paper_today),
            "all": paper_stats(paper_all),
            "by_source": by_source,
        },
        "hello": hello,
        "banners": banners,
    }


def paper_stats_by_window(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-window paper stats from `labels.window`; rows without the label → `unlabelled`."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
        buckets.setdefault(str(labels.get("window") or "unlabelled"), []).append(r)
    return {w: paper_stats(rs) for w, rs in sorted(buckets.items())}


def sessions_view(knowledge: Knowledge, *, now: datetime | None = None) -> dict[str, Any]:
    """Session policy as loaded, the current window, per-window paper stats, calibration
    (k_atr widened from MAE, refuted / eligible classes) and the daily intent spend."""
    from capitalizator.risk.sessions import SessionPolicy

    when = now or datetime.now(tz=UTC)
    policy = SessionPolicy.load()
    state = policy.window(when)
    windows = []
    for w in (*policy.windows, policy.weekend):
        windows.append(
            {
                "name": w.name,
                "start": None if w.name == "weekend" else w.start.isoformat(timespec="minutes"),
                "end": None
                if w.name == "weekend"
                else ("24:00" if w.end_is_midnight else w.end.isoformat(timespec="minutes")),
                "ideas": sorted(w.ideas),
                "size_mult": str(w.size_mult),
                "k_atr": str(w.k_atr),
                "budget": w.budget,
                "symbols": w.symbols,
                "lev_5x_ok": w.lev_5x_ok,
                "closed": not w.ideas or w.budget <= 0 or w.size_mult <= 0,
            }
        )
    paper_all = knowledge.paper_trades() if knowledge.available() else []
    by_window = {
        src: paper_stats_by_window([r for r in paper_all if r.get("source") == src])
        for src in ("shadow", "demo")
    }
    spent: dict[str, int] = {}
    if knowledge.available():
        day = when.date().isoformat()
        for key, raw in knowledge.meta_prefix(f"budget:{day}").items():
            if raw.isdigit():
                spent[key.split(":", 2)[-1]] = int(raw)
    return {
        "at": when.isoformat(),
        "now": {
            "window": state.name,
            "weekend": state.weekend,
            "clock_window": policy.clock_name(when),
            "size_mult": str(state.size_mult),
            "k_atr": str(state.k_atr),
            "budget": state.budget,
            "budget_key": state.budget_key,
            "blackouts": list(policy.active_blackouts(when)),
        },
        "windows": windows,
        "blackouts": [
            {
                "name": b.name,
                "kind": b.kind,
                "start": b.start.isoformat(timespec="minutes"),
                "end": "24:00" if b.end_is_midnight else b.end.isoformat(timespec="minutes"),
                "weekday": b.weekday,
                "applies_to": b.applies_to,
            }
            for b in policy.blackouts
        ],
        "funding_blackout_min": int(policy.funding_blackout.total_seconds() // 60),
        "us_data_day_block_windows": sorted(policy.us_data_block),
        "budget_spent_today": spent,
        "paper_by_window": by_window,
        "k_atr_calibrated": _json(knowledge.meta("k_atr_calibrated"))
        if knowledge.available()
        else None,
        "eligible_windows": _json(knowledge.meta("eligible_windows"))
        if knowledge.available()
        else None,
        "calibration": _json(knowledge.meta("calibration")) if knowledge.available() else None,
        "correlation": _json(knowledge.meta("correlation")) if knowledge.available() else None,
    }


def universe_view(knowledge: Knowledge) -> dict[str, Any]:
    from capitalizator.screener.universe import load_desk_universe

    current = load_desk_universe()
    proposal = _json(knowledge.meta("universe_proposal")) if knowledge.available() else None
    applied = _json(knowledge.meta("universe_applied")) if knowledge.available() else None
    error = knowledge.meta("universe_proposal_error") if knowledge.available() else None
    return {
        "current": list(current.symbols),
        "proposal": proposal,
        "applied": applied,
        "proposal_error": error,
        "apply": (
            "POST /api/universe {proposal_id, ack: true}; takes effect on desk/recorder restart"
        ),
    }


def preview_view(knowledge: Knowledge, *, touch_id: str | None) -> dict[str, Any]:
    """What the desk would send / did send for a touch: entry, stop and why it sits
    there, target, qty, leverage, risk in USDT and %, EV, calibration, session verdict.
    Nothing is recomputed: this is the journal row the desk already wrote."""
    if not knowledge.available():
        return {"touch_id": touch_id, "found": False, "reason": "no knowledge db"}
    row: dict[str, Any] | None = None
    if touch_id:
        row = knowledge.get_journal_touch(touch_id)
    else:
        rows = [r for r in knowledge.journal_rows() if r.get("jury") == "ACCORD"]
        rows.sort(key=lambda r: str(r.get("touch_ts") or ""))
        row = rows[-1] if rows else None
    if row is None:
        return {"touch_id": touch_id, "found": False, "reason": "no such touch"}
    intent: dict[str, Any] | None = None
    intent_id = row.get("intent_id")
    if intent_id is not None:
        for r in knowledge.intent_rows(limit=500):
            if r.get("id") == intent_id:
                intent = r.get("payload") if isinstance(r.get("payload"), dict) else None
                break
    paper = row.get("paper") if isinstance(row.get("paper"), dict) else {}
    return {
        "touch_id": row.get("touch_id"),
        "found": True,
        "symbol": row.get("symbol"),
        "idea": row.get("idea"),
        "side": row.get("idea_side"),
        "jury": row.get("jury"),
        "skip_reason": row.get("skip_reason"),
        "send_skip": row.get("send_skip"),
        "sent": intent is not None,
        "session": {
            "window": row.get("session_window"),
            "weekend": row.get("session_weekend"),
            "gate": row.get("session_gate"),
            "size_mult": row.get("session_size_mult"),
            "k_atr": row.get("session_k_atr"),
        },
        "intent": intent,
        "stop_components": None if intent is None else intent.get("stop_components"),
        "sizing": row.get("sizing"),
        "ev": row.get("ev"),
        "calibration": row.get("calibration"),
        "size_mult_applied": row.get("size_mult_applied"),
        "paper": paper,
    }


def queue_view(knowledge: Knowledge, *, limit: int = 100) -> dict[str, Any]:
    if not knowledge.available():
        return {"intents": [], "orders": [], "oms": [], "counts": {}}
    intents = knowledge.intent_rows(limit=limit)
    orders = knowledge.order_rows(limit=limit)
    oms = knowledge.oms_rows(limit=limit)
    counts: dict[str, int] = {}
    for r in intents:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"intents": intents, "orders": orders, "oms": oms, "counts": counts}
