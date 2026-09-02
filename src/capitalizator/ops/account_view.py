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
        "pnl_net": str(sum((Decimal(str(r.get("realized") or 0)) - Decimal(str(r.get("fees") or 0))
                            - Decimal(str(r.get("funding") or 0)) for r in filled), Decimal("0"))),
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
