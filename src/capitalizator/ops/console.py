"""Laptop console. Bind 127.0.0.1. No orders. No keys.

GET is the desk. POST /contour and POST /api/contour may turn the
recording contour on after hours24. POST /order and every other write stay 405.
"""

from __future__ import annotations

import argparse
import html
import json
import secrets
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from capitalizator.ops import chronos_data, i18n_ru
from capitalizator.ops.contour import ContourNotReady
from capitalizator.ops.contour import enable as enable_contour
from capitalizator.ops.contour import status as contour_status
from capitalizator.ops.daily_map_report import contains_advice, daily_map_report
from capitalizator.ops.desk_chrome import DESK_CSS, nav_html, render_glossary_html
from capitalizator.ops.knowledge import Knowledge, open_knowledge
from capitalizator.ops.latency import decision_report
from capitalizator.ops.phase import load_phase, trading_mode
from capitalizator.ops.product import (
    HelloRequired,
    KeysRequired,
    LiveGateClosed,
    cred_present,
    hello_recorded,
    read_user_mode,
    set_user_mode,
)
from capitalizator.ops.settings import (
    Settings,
    add_source,
    load_sources,
    remove_source,
    set_source_enabled,
)
from capitalizator.ops.settings_page import render_settings_html
from capitalizator.ops.touch_screen import latest as latest_touch
from capitalizator.ops.touch_screen import render_html as render_touch_html
from capitalizator.ops.vault import (
    Vault,
    init_vault,
    iter_regular_files,
    load_vault,
    open_regular,
)
from capitalizator.ops.wake import desk_wake, idle
from capitalizator.risk.session import load_time_config
from capitalizator.screener.universe import load_desk_universe

ADVICE_WORDS = ("лонг", "шорт", "купи", "продай", "завтра")

VENDOR_DIR = Path(__file__).with_name("vendor")
VENDOR_TYPES = {
    "lightweight-charts.standalone.production.js": "application/javascript; charset=utf-8",
    "gsap.min.js": "application/javascript; charset=utf-8",
    "EasePack.min.js": "application/javascript; charset=utf-8",
    "pixi.min.js": "application/javascript; charset=utf-8",
}


def vendor_file(name: str) -> tuple[bytes, str] | None:
    """Local UMD engines. Allowlisted names only — no path walk."""
    if not name or name not in VENDOR_TYPES:
        return None
    path = VENDOR_DIR / name
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    return data, VENDOR_TYPES[name]


class ThreadedHTTPServer(ThreadingHTTPServer):
    """SSE holds a GET open; without threads every other console request freezes."""

    daemon_threads = True
    allow_reuse_address = True


def _parquet_counts(tape: Path) -> tuple[int, int]:
    if tape.is_symlink():
        raise ValueError(f"symlink: {tape}")
    if not tape.is_dir():
        return 0, 0
    files = [path for path in iter_regular_files(tape) if path.suffix == ".parquet"]
    # A live desk writes thousands of hour parts. Opening each with pyarrow on
    # every /api/status (SSE refresh) ate ~2.7GiB and killed a 4GiB VPS.
    if len(files) > 128:
        return len(files), 0
    readable = 0
    rows = 0
    if files:
        import os

        import pyarrow.parquet as pq

        for path in files:
            fd = open_regular(path)
            with os.fdopen(fd, "rb") as fh:
                try:
                    meta = pq.ParquetFile(fh).metadata
                except (OSError, ValueError):
                    continue
            if meta is None:
                continue
            readable += 1
            rows += int(meta.num_rows)
    return readable, rows


def _crosstab(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (
            str(row.get("cav_label") or "—"),
            str(row.get("zlg_label") or "—"),
            str(row.get("outcome") or "—"),
        )
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {"cav": cav, "zlg": zlg, "outcome": outcome, "n": n}
        for (cav, zlg, outcome), n in sorted(buckets.items())
    ]


def _latency_decision(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    try:
        return decision_report(rows)
    except ValueError:
        return None


def _jury_today(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, int] = {}
    for row in rows:
        label = str(row.get("jury") or "—")
        buckets[label] = buckets.get(label, 0) + 1
    return [{"jury": label, "n": n} for label, n in sorted(buckets.items())]


def _desk_taps() -> dict[str, Any]:
    """§7 краны: time.yaml + phase.yaml, read-only, no yaml write."""
    time_cfg = load_time_config()
    phase = load_phase()
    return {
        "dead_man_s": int(time_cfg["dead_man_s"]),
        "reconcile_s": int(time_cfg["reconcile_s"]),
        "first_minute_s": int(time_cfg["first_minute_s"]),
        "max_lev": int(phase["max_lev"]),
        "target_risk": float(phase["target_risk"]),
    }


def desk_snapshot(vault: Vault, *, day: str | None = None) -> dict[str, Any]:
    n_days = None
    n_touches = 0
    journal: list[dict[str, Any]] = []
    overlays: list[dict[str, str | None]] = []
    touch_snap: dict[str, Any] | None = None
    knowledge = open_knowledge(vault, create=False)
    try:
        counts = knowledge.counts()
        chain_ok = knowledge.verify_ok()
        episodes = knowledge.episodes()
        latest = knowledge.latest_report()
        report_body = None
        report_day = day
        if day:
            report_body = knowledge.report(day=day, kind="map")
        if report_body is None and latest is not None:
            report_body = latest["body"]
            report_day = latest["day"]
        raw_n = knowledge.meta("learn_n_days")
        if raw_n is not None:
            n_days = int(raw_n)
        if knowledge.available():
            journal = knowledge.journal_rows()
            overlays = knowledge.overlay_rows()
            n_touches = len(journal)
        touch_snap = latest_touch(knowledge) if knowledge.available() else None
    finally:
        knowledge.close()
    files_n, rows_n = _parquet_counts(vault.tape)
    from capitalizator.ops.account_view import account_view, queue_view

    knowledge = open_knowledge(vault, create=False)
    try:
        money = account_view(knowledge)
        queue = queue_view(knowledge, limit=50)
        raw_blocked = knowledge.meta("entries_blocked") if knowledge.available() else None
    finally:
        knowledge.close()
    try:
        entries_blocked = json.loads(raw_blocked) if raw_blocked else []
    except json.JSONDecodeError:
        entries_blocked = []
    if report_body is None:
        report_body = daily_map_report(day=report_day or "нет даты", rows=[])
        report_day = report_day or "нет даты"
    mode = trading_mode()
    contour = contour_status(vault)
    user = read_user_mode(vault)
    hello_ok = hello_recorded(vault)
    banners: list[str] = []
    if knowledge.available() and knowledge.meta("desk_backlog") == "1":
        banners.append("Стол догоняет ленту после рестарта: метки исторические, входов нет")
    if not hello_ok:
        banners.append("Демо: нет hello")
    if n_touches < 20:
        banners.append("мало n")
    banners.extend(money["banners"])
    banner = " — ".join(banners)
    symbols = list(load_desk_universe().symbols)
    snap = {
        "trading_mode": mode,
        "user_mode": user,
        "hello_ok": hello_ok,
        "hello_banner": banner,
        "n_banner": "мало n" if n_touches < 20 else "",
        "symbols": symbols,
        "n_symbols": len(symbols),
        "learn_n_days": n_days,
        "n_touches": n_touches,
        "contour": contour["contour"],
        "hours24": contour["hours24"],
        "hours24_span_s": contour["hours24_span_s"],
        "hours24_source": contour.get("hours24_source"),
        "hours24_detail": contour.get("hours24_detail"),
        "can_enable": contour["can_enable"],
        "n_hash": counts["hash_links"],
        "n_episode": counts["episodes"],
        "n_report": counts["reports"],
        "hash_chain_ok": chain_ok,
        "parquet_files": files_n,
        "parquet_rows": rows_n,
        "episodes": episodes,
        "report_day": report_day,
        "report": report_body,
        "honest": "пусто — не выдумка" if counts["episodes"] == 0 else "есть строки журнала",
        "tape_holes": 0 if contour["hours24"] else 1,
        "cav_zlg": _crosstab(journal),
        "jury_today": _jury_today(journal),
        "shadow_vs_demo_vs_live": {
            "shadow": sum(1 for row in journal if row.get("shadow_would")),
            "demo": sum(1 for row in episodes if row.get("mode") == "demo"),
            "live": sum(1 for row in episodes if row.get("mode") == "live"),
            "overlay": overlays,
        },
        "taps": _desk_taps(),
        "entries_blocked": entries_blocked if isinstance(entries_blocked, list) else [],
        "learning": _learning_snapshot(vault),
        "touch": touch_snap,
        "last_price": chronos_data.last_prices(vault),
        "session_window": chronos_data.session_window(),
        "last_jury": chronos_data.last_jury(vault),
        "money": money,
        "queue_counts": queue["counts"],
        "banners": banners,
        "latency_decision": _latency_decision(journal),
    }
    text = json.dumps(snap, ensure_ascii=False)
    if contains_advice(text):
        raise ValueError("console snapshot must not advise")
    return snap


def _page(snap: dict[str, Any], *, token: str = "") -> str:
    template = (Path(__file__).with_name("chronos.html")).read_text(encoding="utf-8")
    taps = snap.get("taps") or {}
    hours24 = bool(snap.get("hours24"))
    can_enable = bool(snap.get("can_enable"))
    if snap.get("contour") == "on":
        contour_note = "Контур включён. Метки пишутся. Ордеров нет."
        contour_form = ""
    elif hours24:
        disabled = "" if can_enable else " disabled"
        contour_note = "Сутки ленты есть. Кнопка включает запись меток, не торги."
        contour_form = (
            '<form method="post" action="/contour">'
            '<input type="hidden" name="action" value="on"/>'
            f'<input type="hidden" name="ack_token" value="{html.escape(token)}"/>'
            f'<button type="submit"{disabled}>Включить контур</button>'
            "</form>"
        )
    else:
        contour_note = "Контур выключен. Суток ленты нет."
        contour_form = (
            '<form method="post" action="/contour">'
            '<input type="hidden" name="action" value="on"/>'
            f'<input type="hidden" name="ack_token" value="{html.escape(token)}"/>'
            '<button type="submit" disabled>Включить контур</button>'
            "</form>"
        )
    def _term(code: object) -> str:
        """Русское название + код, подсказка по наведению."""
        title = html.escape(i18n_ru.hint(code))
        return f'<span title="{title}">{html.escape(i18n_ru.ru(code))}</span>'


    cav_rows = snap.get("cav_zlg") or []
    if cav_rows:
        cav_html = "".join(
            (
                "<tr>"
                f"<td>{_term(r['cav'])}</td>"
                f"<td>{_term(r['zlg'])}</td>"
                f"<td>{_term(r['outcome'])}</td>"
                f"<td>{int(r['n'])}</td>"
                "</tr>"
            )
            for r in cav_rows
        )
    else:
        cav_html = '<tr><td colspan="4" class="empty">Свеча × Книга × Исход — пока пусто</td></tr>'
    jury_rows = snap.get("jury_today") or []
    if jury_rows:
        jury_html = "".join(
            f"<li>{_term(r['jury'])}: {int(r['n'])}</li>" for r in jury_rows
        )
    else:
        jury_html = '<li class="empty">решений жюри сегодня нет</li>'
    vs = snap.get("shadow_vs_demo_vs_live") or {}
    learn_n = snap.get("learn_n_days")
    learn_txt = "—" if learn_n is None else str(learn_n)
    money = snap.get("money") or {}
    acct = money.get("account") or {}
    exch = money.get("exchange") or {}
    banner_items = "".join(
        f"<li class=\"warn\">{html.escape(str(b))}</li>" for b in (money.get("banners") or [])
    ) or '<li class="empty">предупреждений нет</li>'
    positions = exch.get("positions") or acct.get("open") or []
    pos_html = "".join(
        "<tr>"
        f"<td>{html.escape(str(p.get('symbol')))}</td>"
        f"<td>{html.escape(str(p.get('side')))}</td>"
        f"<td>{html.escape(str(p.get('size', p.get('qty'))))}</td>"
        f"<td>{html.escape(str(p.get('avg_price', p.get('entry'))))}</td>"
        f"<td>{html.escape(str(p.get('stop_loss', p.get('stop'))))}</td>"
        f"<td>{html.escape(str(p.get('liq_price', '—')))}</td>"
        f"<td>{html.escape(str(p.get('unrealised_pnl', '—')))}</td>"
        "</tr>"
        for p in positions
    ) or '<tr><td colspan="7" class="empty">позиций нет</td></tr>'

    def _pct(raw: object) -> str:
        try:
            return f"{float(str(raw)) * 100:+.2f}%"
        except (TypeError, ValueError):
            return "—"

    equity_line = (
        f"эквити {html.escape(str(acct.get('equity', '—')))} "
        f"({html.escape(str(acct.get('equity_source', 'нет данных')))}) · "
        f"биржа: {html.escape(str(exch.get('equity', 'не читалось')))}"
    )
    def _e(value: object) -> str:
        return html.escape(str(value))

    halt_txt = _e(acct.get("halt_reason") or "открыт")
    blocked_txt = _e(
        ", ".join(i18n_ru.ru(b) for b in (snap.get("entries_blocked") or [])) or "не заблокированы"
    )
    queue_txt = _e(json.dumps(snap.get("queue_counts") or {}, ensure_ascii=False))
    learn = snap.get("learning") or {}
    drift = learn.get("drift") or {}
    exam = learn.get("exam") or {}
    oko_n = learn.get("oko") or {}
    learn_block = (
        "<h2>Учёба (контур C и ОКО)</h2>"
        f"<p>дрейф: {'есть' if drift.get('drift') else 'нет'} (n={_e(drift.get('n', 0))}, "
        f"целевой риск {_e(drift.get('target_risk', '—'))}) · классов в калибровке: "
        f"{_e(learn.get('calibration_classes', 0))} · экзамен претендента: "
        f"{'пройден' if exam.get('passed') else 'не пройден'}"
        f" (n чемпиона {_e((exam.get('champion') or {}).get('n', 0))}, "
        f"n претендента {_e((exam.get('challenger') or {}).get('n', 0))})</p>"
        f"<p>паспорта ОКО: {_e(oko_n.get('passports', 0))} (зрелых {_e(oko_n.get('mature', 0))}) · "
        f"память ловушек: {_e(oko_n.get('memory', 0))} · Зеркало: "
        f"{'пройдено' if oko_n.get('mirror_passed') else 'не пройдено / нет'} · "
        f"сентимент (F&G): {_e(learn.get('sentiment', '—'))} · intel-элементов: "
        f"{_e(learn.get('intel_items', 0))}</p>"
        + (
            "<p class='warn'>ОКО: органы, не прочитанные при старте (начали с нуля): "
            + _e(", ".join(sorted(learn.get("oko_load_errors") or {})))
            + "</p>"
            if learn.get("oko_load_errors")
            else ""
        )
    )
    money_block = f"""{learn_block}<h2>Счёт</h2>
      <p>{equity_line}</p>
      <p>день {_pct(acct.get("day_pnl_pct"))} · неделя {_pct(acct.get("week_pnl_pct"))}
      · просадка от пика {_pct(acct.get("drawdown_from_peak"))} · кран: {halt_txt}</p>
      <h2>Позиции</h2>
      <table><thead><tr><th>символ</th><th>сторона</th><th>размер</th><th>вход</th>
      <th>стоп (биржа)</th><th>ликвидация</th><th>uPnL</th></tr></thead>
      <tbody>{pos_html}</tbody></table>
      <p>очередь интентов: {queue_txt}</p>
      <h2>Предупреждения</h2><ul>{banner_items}</ul>"""
    service = f"""<div id="service">
      <h2>Стол: счёт, позиции, учёба, предупреждения (факты из журнала)</h2>
      {money_block}
      <h2>Свеча (CAV) × Книга (ZLG) × Исход</h2>
      <table><tbody>{cav_html}</tbody></table>
      <h2>Жюри дня</h2><ul>{jury_html}</ul>
      <p><a href="/ops">Управление: команды, риск-меню, сессии, вселенная</a>
      · <a href="/settings">Настройки: ключи и источники</a>
      · <a href="/api/glossary">Словарь кодов (JSON)</a> · входы: {blocked_txt}</p>
      <p>n касаний {int(snap.get("n_touches") or 0)}</p>
      <p>День учёбы {html.escape(learn_txt)}</p>
      <p>Дыры ленты {int(snap.get("tape_holes") or 0)}</p>
      <p>тень {int(vs.get("shadow") or 0)} демо {int(vs.get("demo") or 0)}
      лайв {int(vs.get("live") or 0)}</p>
      <p>Краны dead_man_s: {int(taps.get("dead_man_s") or 0)}
      reconcile_s: {int(taps.get("reconcile_s") or 0)}
      first_minute_s: {int(taps.get("first_minute_s") or 0)}
      max_lev: {int(taps.get("max_lev") or 0)}
      target_risk: {taps.get("target_risk")}</p>
      <p>{html.escape(contour_note)}</p>
      {contour_form}
      <p>{" ".join(html.escape(str(s)) for s in (snap.get("symbols") or []))}</p>
    </div>"""
    boot = json.dumps(
        {
            "symbols": snap.get("symbols") or [],
            "user_mode": snap.get("user_mode") or "off",
            "last_price": snap.get("last_price") or {},
            "session_window": snap.get("session_window") or {},
            "ack_token": token,
        },
        ensure_ascii=False,
    )
    page = (
        template.replace("{{SERVICE}}", service)
        .replace("{{BOOT}}", boot)
        .replace("{{DESK_CSS}}", DESK_CSS)
        .replace("{{NAV}}", nav_html("stol"))
    )
    return page


def _json_or(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _learning_snapshot(vault: Vault) -> dict[str, Any]:
    """Contour C / ОКО facts for the operator: drift, calibration, exam, passports."""
    knowledge = open_knowledge(vault, create=False)
    try:
        if not knowledge.available():
            return {}

        def _j(key: str) -> Any:
            raw = knowledge.meta(key)
            if not raw:
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None

        calib = _j("calibration") or {}
        passports = knowledge.meta_prefix("oko:passport:")
        mature = 0
        for raw in passports.values():
            try:
                if len(json.loads(raw).get("depth") or []) >= 30:
                    mature += 1
            except (json.JSONDecodeError, AttributeError):
                continue
        memory = 0
        for raw in knowledge.meta_prefix("oko:memory:").values():
            try:
                memory += len(json.loads(raw).get("records") or [])
            except (json.JSONDecodeError, AttributeError):
                continue
        mirror = _j("oko:mirror") or {}
        sentiment = _j("sentiment") or {}
        return {
            "drift": _j("drift") or {},
            "calibration_classes": len(calib) if isinstance(calib, dict) else 0,
            "exam": _j("exam_last") or _j("exam_night") or {},
            "champion_candidate": _j("champion_candidate"),
            "oko": {
                "passports": len(passports),
                "mature": mature,
                "memory": memory,
                "mirror_passed": bool(mirror.get("passed")) if isinstance(mirror, dict) else False,
            },
            "sentiment": sentiment.get("value") if isinstance(sentiment, dict) else None,
            "intel_items": len(knowledge.intel_items(limit=100_000)),
            "oko_load_errors": _json_or(knowledge.meta("oko_load_errors"), {}),
        }
    finally:
        knowledge.close()


def _int_arg(qs: dict[str, list[str]], name: str, default: int) -> int:
    raw = (qs.get(name) or [None])[0]
    if raw in {None, ""}:
        return default
    return int(raw)


def _api_get(vault: Vault, path: str, qs: dict[str, list[str]]) -> dict[str, Any] | None:
    symbol = (qs.get("symbol") or [None])[0]
    if path == "/api/hello/status":
        return chronos_data.hello_status(vault)
    if path == "/api/bars":
        tf = (qs.get("tf") or ["15m"])[0] or "15m"
        limit = _int_arg(qs, "limit", 200)
        try:
            bars = chronos_data.bars_for(vault, symbol=symbol or "", tf=tf, limit=limit)
        except ValueError:
            return {"symbol": symbol or "", "tf": tf, "bars": []}
        return {"symbol": symbol or "", "tf": tf, "bars": bars}
    if path == "/api/zones":
        return {"symbol": symbol or "", "zones": chronos_data.zones_for(vault, symbol=symbol or "")}
    if path == "/api/book":
        return chronos_data.book_for(vault, symbol=symbol or "")
    if path == "/api/replay":
        return chronos_data.replay_for(vault, symbol=symbol or "")
    if path == "/api/trades":
        limit = _int_arg(qs, "limit", 50)
        trades = chronos_data.trades_for(vault, symbol=symbol or "", limit=limit)
        return {"symbol": symbol or "", "trades": trades}
    if path == "/api/touch/latest":
        return {"touch": chronos_data.latest_touch(vault, symbol=symbol)}
    if path == "/api/dashboard":
        return chronos_data.dashboard(vault)
    if path == "/api/news":
        return {"events": chronos_data.news_rows()}
    if path == "/api/authors":
        return {
            "posts": chronos_data.author_rows(vault),
            "sources": chronos_data.author_sources(vault),
        }
    if path == "/api/llm_summary":
        return chronos_data.llm_summary(vault)
    if path == "/api/gates":
        from capitalizator.ops.gates_from_sqlite import gates_from_sqlite

        knowledge = open_knowledge(vault, create=False)
        try:
            return gates_from_sqlite(knowledge)
        finally:
            knowledge.close()
    if path == "/api/glossary":
        return {"terms": i18n_ru.glossary(), "columns": i18n_ru.COLUMNS}
    if path == "/api/settings":
        knowledge = open_knowledge(vault, create=False)
        try:
            return {"fields": Settings(vault).view(), "sources": load_sources(knowledge)}
        finally:
            knowledge.close()
    if path == "/api/sources":
        knowledge = open_knowledge(vault, create=False)
        try:
            return {"sources": load_sources(knowledge)}
        finally:
            knowledge.close()
    if path in {"/api/account", "/api/queue", "/api/paper", "/api/risk", "/api/commands"}:
        from capitalizator.ops.account_view import account_view, queue_view
        from capitalizator.risk.config import load_risk_config

        knowledge = open_knowledge(vault, create=False)
        try:
            if path == "/api/account":
                return account_view(knowledge)
            if path == "/api/queue":
                return queue_view(knowledge, limit=_int_arg(qs, "limit", 100))
            if path == "/api/paper":
                source = (qs.get("source") or [None])[0]
                return {
                    "trades": knowledge.paper_trades(
                        source=source, limit=_int_arg(qs, "limit", 200)
                    )
                }
            if path == "/api/commands":
                return {"commands": knowledge.commands(limit=_int_arg(qs, "limit", 100))}
            return {"risk_config": load_risk_config(knowledge).to_payload()}
        finally:
            knowledge.close()
    if path in {"/api/universe", "/api/sessions", "/api/preview"}:
        from capitalizator.ops.account_view import preview_view, sessions_view, universe_view

        knowledge = open_knowledge(vault, create=False)
        try:
            if path == "/api/universe":
                return universe_view(knowledge)
            if path == "/api/sessions":
                return sessions_view(knowledge)
            touch_id = (qs.get("touch_id") or [None])[0]
            return preview_view(knowledge, touch_id=touch_id)
        finally:
            knowledge.close()
    return None


def render_ops(app: ConsoleApp, *, message: str | None = None) -> str:
    """«Управление»: every operator capability as a form, current facts beside it."""
    from capitalizator.ops.account_view import sessions_view, universe_view
    from capitalizator.ops.ops_page import render_ops_html
    from capitalizator.risk.config import load_risk_config

    status = desk_snapshot(app.vault)
    knowledge = open_knowledge(app.vault, create=False)
    try:
        keys = (
            "exchange_state", "entries_blocked_since", "window_drift", "drift", "exam_last",
            "night_last", "champion_candidate", "entries_paused", "desk_heartbeat",
            "signer_heartbeat", "desk_backlog", "recorder_status", "dead_man_last",
            "signer_requeued", "instruments_error_signer", "instruments_error_recorder",
            "intel_status", "llm_last_error", "reddit_auth_error", "paper_restored",
            "paper_open_error", "oko_load_errors", "latency_decision", "decision_trace",
        )
        meta: dict[str, str | None] = dict.fromkeys(keys)
        if knowledge.available():
            meta = {k: knowledge.meta(k) for k in keys}
        page = render_ops_html(
            token=app.csrf_token,
            status=status,
            risk={"risk_config": load_risk_config(knowledge).to_payload()},
            sessions=sessions_view(knowledge),
            universe=universe_view(knowledge),
            commands=knowledge.commands(limit=40) if knowledge.available() else [],
            meta=meta,
            message=message,
        )
    finally:
        knowledge.close()
    low = page.lower()
    for word in ADVICE_WORDS:
        if word in low:
            raise ValueError("ops page must not advise")
    return page


def render_html(vault: Vault, *, day: str | None = None, token: str = "") -> str:
    page = _page(desk_snapshot(vault, day=day), token=token)
    low = page.lower()
    for word in ADVICE_WORDS:
        if word in low:
            raise ValueError("console page must not advise")
    return page


class ConsoleApp:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        # Per-process CSRF/ack token. Every write must carry it (header `X-Ack-Token`
        # or field `ack_token`); pages embed it, `/api/csrf` hands it to same-origin
        # scripts. A literal "yes" from any browser tab used to be enough (audit A8).
        self.csrf_token = secrets.token_urlsafe(24)

    def healthz(self) -> int:
        return 200

    def turn_on(self) -> dict[str, Any]:
        return enable_contour(self.vault)

    def set_mode(
        self,
        mode: str,
        *,
        ack: bool,
        learn_n_days: int | None = None,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return set_user_mode(
            self.vault, mode, ack=ack, learn_n_days=learn_n_days, override_reason=override_reason
        )

    def prove_hello(self, *, ack: bool, probe_order: bool = False) -> dict[str, Any]:
        """Talk to the venue (wallet, instruments). Sets the hello flag only on success."""
        if not ack:
            raise ValueError("ack required")
        from capitalizator.gateway.keys import load_keys

        keys = load_keys(self.vault)
        if keys is None:
            raise HelloRequired("no keys")
        from capitalizator.gateway import BybitGateway
        from capitalizator.gateway.bybit import make_session

        gateway = BybitGateway(make_session(keys), mode=keys.mode)
        result = gateway.hello(probe_order=probe_order)
        from capitalizator.ops.product import record_hello

        knowledge = open_knowledge(self.vault, create=True)
        try:
            ok = record_hello(self.vault, knowledge, result)
        finally:
            knowledge.close()
        # `real` means the last venue hello succeeded — same as GET /api/hello/status.
        return {"hello": result, "hello_ok": ok, "real": ok}

    def set_risk(self, changes: dict[str, Any], *, ack: bool) -> dict[str, Any]:
        """Operator risk menu (D-12). Validated by RiskConfig; applies to new intents."""
        from capitalizator.risk.config import load_risk_config, save_risk_config

        if not ack:
            raise ValueError("ack required")
        knowledge = open_knowledge(self.vault, create=True)
        try:
            from capitalizator.risk.config import RiskConfig

            current = load_risk_config(knowledge)
            allowed = set(current.to_payload()) - {"version", "config_id"}
            bad = set(changes) - allowed
            if bad:
                raise ValueError(f"unknown risk keys: {sorted(bad)}")
            # Typing lives in RiskConfig.from_payload (Decimal / int / bool words /
            # nullable max_stop_atr) — one parser for the console and the snapshot.
            merged = current.to_payload()
            merged.update(changes)
            merged.pop("config_id", None)
            merged["version"] = current.version + 1
            nxt = RiskConfig.from_payload(merged)
            save_risk_config(knowledge, nxt, ack=True)
            return {"risk_config": nxt.to_payload(), "previous_id": current.config_id}
        finally:
            knowledge.close()

    def alerts_test(self, *, ack: bool) -> dict[str, Any]:
        """Send one test message with the Telegram credentials from Настройки."""
        from capitalizator.ops.alerts import send

        if not ack:
            raise ValueError("ack required")
        values = Settings(self.vault, exclude_prefixes=("bybit.", "llm.", "x.", "reddit.")).load()
        ok, note = send(
            values.get("telegram.bot_token", ""),
            values.get("telegram.chat_id", ""),
            "Capitalizator: тестовое оповещение из консоли",
        )
        return {"ok": ok, "note": note}

    def settings_post(self, path: str, payload: dict[str, Any], *, ack: bool) -> dict[str, Any]:
        """/api/settings: {field: value, ...} (empty value deletes). /api/sources:
        {action: add|enable|disable|remove, kind, value, label | id}."""
        knowledge = open_knowledge(self.vault, create=True)
        try:
            if path == "/api/settings":
                changes = {str(k): str(v) for k, v in payload.items()}
                return Settings(self.vault).update(changes, knowledge=knowledge, ack=ack)
            action = str(payload.get("action") or "add")
            if action == "add":
                return add_source(
                    knowledge,
                    kind=str(payload.get("kind") or ""),
                    value=str(payload.get("value") or ""),
                    label=str(payload.get("label") or ""),
                    ack=ack,
                )
            if action in {"enable", "disable"}:
                ok = set_source_enabled(
                    knowledge, str(payload.get("id") or ""), action == "enable", ack=ack
                )
                return {"updated": ok}
            if action == "remove":
                return {"removed": remove_source(knowledge, str(payload.get("id") or ""), ack=ack)}
            raise ValueError(f"unknown action {action!r}")
        finally:
            knowledge.close()

    def apply_universe(self, proposal_id: str, *, ack: bool) -> dict[str, Any]:
        """Human step: the weekly top-N proposal becomes infra/universe.yaml."""
        from capitalizator.screener.refresh import apply_universe

        if not ack:
            raise ValueError("ack required")
        if not proposal_id:
            raise ValueError("proposal_id required")
        knowledge = open_knowledge(self.vault, create=True)
        try:
            universe = apply_universe(
                knowledge,
                proposal_id=proposal_id,
                ack=True,
                now=datetime.now(tz=UTC),
                universe_path=self.vault.root / "universe.yaml",
            )
            return {
                "universe": list(universe.symbols),
                "proposal_id": proposal_id,
                "takes_effect": "on desk/recorder restart",
            }
        finally:
            knowledge.close()

    def command(
        self, kind: str, *, symbol: str | None, ack: bool, reason: str = ""
    ) -> dict[str, Any]:
        """flatten | release_halts | pause_entries | resume_entries | drift_release
        → picked up by the desk tick. drift_release takes a window name in `symbol` (or ALL)."""
        if not ack:
            raise ValueError("ack required")
        if kind not in Knowledge.COMMAND_KINDS:
            raise ValueError(f"unknown command: {kind}")
        if kind in {"flatten", "ack_position"} and not symbol:
            raise ValueError(f"{kind} needs a symbol" + (" (or ALL)" if kind == "flatten" else ""))
        knowledge = open_knowledge(self.vault, create=True)
        try:
            now = datetime.now(tz=UTC).isoformat()
            cmd = {"kind": kind, "symbol": symbol, "reason": reason or "operator", "at": now}
            cmd_id = knowledge.enqueue_command(kind, cmd, created_ts=now)
            pending = sum(1 for c in knowledge.commands(limit=500) if c["status"] == "pending")
            return {"queued": {**cmd, "id": cmd_id}, "pending": pending}
        finally:
            knowledge.close()


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    raw_len = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_len)
    except ValueError as exc:
        raise ValueError("bad content length") from exc
    if length < 0 or length > 4096:
        raise ValueError("bad content length")
    body = handler.rfile.read(length) if length else b""
    ctype = (handler.headers.get("Content-Type") or "").split(";")[0].strip()
    if ctype == "application/json":
        payload = json.loads(body.decode() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("json must be an object")
        return payload
    parsed = parse_qs(body.decode(), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _read_action(handler: BaseHTTPRequestHandler) -> str:
    payload = _read_body(handler)
    return str(payload.get("action") or "")


def _is_local(handler: BaseHTTPRequestHandler) -> bool:
    host = handler.client_address[0]
    return host in {"127.0.0.1", "localhost", "::1"}


_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _write_allowed(handler: BaseHTTPRequestHandler) -> str | None:
    """None when the write may proceed, else the refusal reason.

    Peer must be loopback; `Host` must be a loopback host (DNS rebinding); when a
    browser sends `Origin` it must be a loopback origin (cross-site form/XHR).
    """
    if not _is_local(handler):
        return "localhost only"
    host = (handler.headers.get("Host") or "").split(":")[0].lower()
    if host and host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
        return "bad host"
    origin = handler.headers.get("Origin")
    if origin:
        try:
            o_host = urlparse(origin).hostname or ""
        except ValueError:
            return "bad origin"
        if o_host not in {"127.0.0.1", "localhost", "::1"}:
            return "bad origin"
    return None


def _token_ok(app: ConsoleApp, handler: BaseHTTPRequestHandler, payload: dict[str, Any]) -> bool:
    given = handler.headers.get("X-Ack-Token") or payload.get("ack_token")
    return isinstance(given, str) and secrets.compare_digest(given, app.csrf_token)


def _handler(app: ConsoleApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _reject_write(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "GET, POST")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"read-only")

        def _send(
            self,
            code: int,
            body: bytes,
            ctype: str,
            *,
            extra: dict[str, str] | None = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _turn_on_json(self) -> None:
            try:
                payload = app.turn_on()
                body = json.dumps(payload, ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            except ContourNotReady:
                snap = desk_snapshot(app.vault)
                payload = {
                    "ok": False,
                    "contour": snap["contour"],
                    "hours24": snap["hours24"],
                    "hours24_span_s": snap["hours24_span_s"],
                    "trading_mode": snap["trading_mode"],
                    "can_enable": snap["can_enable"],
                }
                body = json.dumps(payload, ensure_ascii=False).encode()
                self._send(409, body, "application/json; charset=utf-8")

        def _set_mode(self, payload: dict[str, Any], *, redirect: bool) -> None:
            ack = _token_ok(app, self, payload)
            mode = str(payload.get("mode") or "")
            raw_n = payload.get("learn_n_days")
            learn_n = int(raw_n) if raw_n not in {None, ""} else None
            if mode == "learn" and learn_n is None:
                learn_n = 14
            if not ack:
                self._send(403, b"ack required", "text/plain; charset=utf-8")
                return
            if mode in {"demo", "live"} and not hello_recorded(app.vault):
                self._send(403, b"hello required", "text/plain; charset=utf-8")
                return
            if mode == "live" and not cred_present(app.vault):
                self._send(403, b"cred required", "text/plain; charset=utf-8")
                return
            reason = payload.get("override_reason")
            try:
                out = app.set_mode(
                    mode, ack=True, learn_n_days=learn_n,
                    override_reason=None if reason in {None, ""} else str(reason),
                )
            except LiveGateClosed as exc:
                self._send(409, str(exc).encode(), "text/plain; charset=utf-8")
                return
            except KeysRequired:
                self._send(403, b"cred required", "text/plain; charset=utf-8")
                return
            except HelloRequired:
                self._send(403, b"hello required", "text/plain; charset=utf-8")
                return
            except ValueError as exc:
                self._send(400, str(exc).encode(), "text/plain; charset=utf-8")
                return
            if redirect:
                self._send(303, b"", "text/plain; charset=utf-8", extra={"Location": "/"})
                return
            body = json.dumps(out, ensure_ascii=False).encode()
            self._send(200, body, "application/json; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            sent = False
            try:
                path = urlparse(self.path).path
                denied = _write_allowed(self)
                if denied is not None:
                    self._send(403, denied.encode(), "text/plain; charset=utf-8")
                    return
                if path in {"/api/mode", "/mode"}:
                    try:
                        payload = _read_body(self)
                    except (ValueError, json.JSONDecodeError):
                        self._send(400, b"bad-mode", "text/plain; charset=utf-8")
                        return
                    self._set_mode(payload, redirect=path == "/mode")
                    return
                if path == "/api/hello":
                    try:
                        payload = _read_body(self)
                    except (ValueError, json.JSONDecodeError):
                        self._send(400, b"bad-json", "text/plain; charset=utf-8")
                        return
                    if not _token_ok(app, self, payload):
                        self._send(403, b"ack required", "text/plain; charset=utf-8")
                        return
                    probe = payload.get("probe_order") in {"1", "true", True}
                    try:
                        out = app.prove_hello(ack=True, probe_order=probe)
                    except HelloRequired:
                        self._send(403, b"no keys", "text/plain; charset=utf-8")
                        return
                    except ImportError:
                        self._send(503, b"gateway extra not installed", "text/plain; charset=utf-8")
                        return
                    except Exception:
                        self._send(502, b"hello failed", "text/plain; charset=utf-8")
                        return
                    if payload.get("redirect") in {"1", "true", True}:
                        note = (
                            "биржа ответила"
                            if out.get("hello_ok")
                            else "биржа не подтвердила ключ"
                        )
                        self._send(
                            303, b"", "text/plain; charset=utf-8",
                            extra={"Location": "/settings?msg=" + quote(note)},
                        )
                        return
                    body = json.dumps(out, ensure_ascii=False, default=str).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                    return
                if path == "/api/alerts/test":
                    try:
                        payload = _read_body(self)
                    except (ValueError, json.JSONDecodeError):
                        self._send(400, b"bad-json", "text/plain; charset=utf-8")
                        return
                    ack = _token_ok(app, self, payload)
                    try:
                        out = app.alerts_test(ack=ack)
                    except ValueError as exc:
                        self._send(403, str(exc).encode(), "text/plain; charset=utf-8")
                        return
                    if payload.get("redirect") in {"1", "true"}:
                        note = (
                            "Telegram: отправлено" if out["ok"]
                            else f"Telegram: отказ ({out['note']})"
                        )
                        self._send(
                            303, b"", "text/plain; charset=utf-8",
                            extra={"Location": "/settings?msg=" + quote(note)},
                        )
                        return
                    self._send(200, json.dumps(out).encode(), "application/json; charset=utf-8")
                    return
                if path in {"/api/settings", "/api/sources"}:
                    try:
                        payload = _read_body(self)
                    except (ValueError, json.JSONDecodeError):
                        self._send(400, b"bad-json", "text/plain; charset=utf-8")
                        return
                    ack = _token_ok(app, self, payload)
                    payload.pop("ack_token", None)
                    payload.pop("ack", None)
                    payload.pop("confirm", None)  # settings page checkbox; not a field
                    redirect = payload.pop("redirect", None) in {"1", "true", True}
                    # HTML form: empty input = leave unchanged (settings_page.py).
                    # JSON still deletes on "" — that path is the explicit wipe API.
                    ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
                    if path == "/api/settings" and ctype != "application/json":
                        payload = {
                            k: v for k, v in payload.items() if str(v).strip() != ""
                        }
                    try:
                        out = app.settings_post(path, payload, ack=ack)
                    except ValueError as exc:
                        code = 403 if "ack" in str(exc) else 400
                        self._send(code, str(exc).encode(), "text/plain; charset=utf-8")
                        return
                    if redirect:
                        self._send(
                            303, b"", "text/plain; charset=utf-8", extra={"Location": "/settings"}
                        )
                        return
                    body = json.dumps(out, ensure_ascii=False, default=str).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                    return
                if path in {"/api/risk", "/api/command", "/api/universe"}:
                    try:
                        payload = _read_body(self)
                    except (ValueError, json.JSONDecodeError):
                        self._send(400, b"bad-json", "text/plain; charset=utf-8")
                        return
                    ack = _token_ok(app, self, payload)
                    payload.pop("ack_token", None)
                    payload.pop("ack", None)
                    payload.pop("confirm", None)  # «Управление» checkbox; not a field
                    redirect = payload.pop("redirect", None) in {"1", "true", True}
                    if path == "/api/risk" and redirect:
                        # HTML form: empty input = leave unchanged
                        payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
                    try:
                        if path == "/api/risk":
                            out = app.set_risk(payload, ack=ack)
                            note = f"риск-меню сохранено, версия {out['risk_config']['version']}"
                        elif path == "/api/universe":
                            out = app.apply_universe(
                                str(payload.get("proposal_id") or ""), ack=ack
                            )
                            note = "вселенная применена; вступит после рестарта стола и рекордера"
                        else:
                            out = app.command(
                                str(payload.get("kind") or ""),
                                symbol=payload.get("symbol"),
                                ack=ack,
                                reason=str(payload.get("reason") or ""),
                            )
                            note = f"команда поставлена в очередь (#{out['queued']['id']})"
                    except ValueError as exc:
                        code = 403 if "ack" in str(exc) else 400
                        if redirect:
                            self._send(
                                303, b"", "text/plain; charset=utf-8",
                                extra={"Location": "/ops?msg=" + quote(f"отказ: {exc}")},
                            )
                            return
                        self._send(code, str(exc).encode(), "text/plain; charset=utf-8")
                        return
                    if redirect:
                        self._send(
                            303, b"", "text/plain; charset=utf-8",
                            extra={"Location": "/ops?msg=" + quote(note)},
                        )
                        return
                    body = json.dumps(out, ensure_ascii=False, default=str).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                    return
                if path not in {"/contour", "/api/contour"}:
                    self._reject_write()
                    return
                try:
                    payload = _read_body(self)
                    action = str(payload.get("action") or "")
                except (ValueError, json.JSONDecodeError):
                    self._send(400, b"bad-action", "text/plain; charset=utf-8")
                    return
                if not _token_ok(app, self, payload):
                    self._send(403, b"ack token required", "text/plain; charset=utf-8")
                    return
                if action != "on":
                    self._send(400, b"bad-action", "text/plain; charset=utf-8")
                    return
                if path == "/api/contour":
                    self._turn_on_json()
                    return
                try:
                    app.turn_on()
                    sent = True
                    self._send(
                        303,
                        b"",
                        "text/plain; charset=utf-8",
                        extra={"Location": "/"},
                    )
                except ContourNotReady:
                    body = render_html(app.vault, token=app.csrf_token).encode()
                    sent = True
                    self._send(409, body, "text/html; charset=utf-8")
            except Exception:
                if sent:
                    return
                try:
                    self._send(500, b"error", "text/plain; charset=utf-8")
                except Exception:
                    return

        def do_PUT(self) -> None:  # noqa: N802
            self._reject_write()

        def do_DELETE(self) -> None:  # noqa: N802
            self._reject_write()

        def do_PATCH(self) -> None:  # noqa: N802
            self._reject_write()

        def _sse_desk(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            wake = desk_wake(app.vault)
            ping = json.dumps({"refresh": True}, ensure_ascii=False)
            while True:
                try:
                    self.wfile.write(f"data: {ping}\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
                idle(wake, 8.0)

        def do_GET(self) -> None:  # noqa: N802
            started = False
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/stream":
                    self._sse_desk()
                    return
                if path == "/healthz":
                    from capitalizator.ops.healthz import heartbeat_age_s

                    age = heartbeat_age_s(app.vault.root, "desk_heartbeat")
                    if age is None:
                        body = b"ok"
                    else:
                        body = f"ok {age:.0f}s".encode()
                    code, ctype = 200, "text/plain; charset=utf-8"
                elif path == "/api/status":
                    payload = desk_snapshot(app.vault)
                    body = json.dumps(payload, ensure_ascii=False).encode()
                    code, ctype = 200, "application/json; charset=utf-8"
                elif path == "/api/csrf":
                    # same-origin scripts only can read this (no CORS headers are sent)
                    if not _is_local(self):
                        body, code, ctype = b"localhost only", 403, "text/plain; charset=utf-8"
                    else:
                        body = json.dumps({"ack_token": app.csrf_token}).encode()
                        code, ctype = 200, "application/json; charset=utf-8"
                elif path.startswith("/api/"):
                    payload = _api_get(app.vault, path, parse_qs(parsed.query))
                    if payload is None:
                        body, code, ctype = b"not-found", 404, "text/plain; charset=utf-8"
                    else:
                        raw = json.dumps(payload, ensure_ascii=False)
                        if contains_advice(raw):
                            raise ValueError("console snapshot must not advise")
                        body = raw.encode()
                        code, ctype = 200, "application/json; charset=utf-8"
                elif path in {"/", "/index.html"}:
                    qs = parse_qs(parsed.query)
                    day = qs.get("day", [None])[0]
                    body = render_html(app.vault, day=day, token=app.csrf_token).encode()
                    code, ctype = 200, "text/html; charset=utf-8"
                elif path == "/touch":
                    snap = desk_snapshot(app.vault)
                    body = render_touch_html(snap.get("touch")).encode()
                    code, ctype = 200, "text/html; charset=utf-8"
                elif path == "/ops":
                    msg = (parse_qs(parsed.query).get("msg") or [None])[0]
                    body = render_ops(app, message=msg).encode()
                    code, ctype = 200, "text/html; charset=utf-8"
                elif path == "/settings":
                    knowledge = open_knowledge(app.vault, create=False)
                    try:
                        body = render_settings_html(
                            Settings(app.vault).view(), load_sources(knowledge),
                            token=app.csrf_token,
                            message=(parse_qs(parsed.query).get("msg") or [None])[0],
                        ).encode()
                    finally:
                        knowledge.close()
                    code, ctype = 200, "text/html; charset=utf-8"
                elif path == "/glossary":
                    qs = parse_qs(parsed.query)
                    body = render_glossary_html(
                        q=(qs.get("q") or [""])[0],
                        group=(qs.get("group") or [""])[0],
                    ).encode()
                    code, ctype = 200, "text/html; charset=utf-8"
                elif path.startswith("/vendor/"):
                    name = unquote(path[len("/vendor/") :]).split("/", 1)[0]
                    got = vendor_file(name)
                    if got is None:
                        body, code, ctype = b"not-found", 404, "text/plain; charset=utf-8"
                    else:
                        body, ctype = got
                        code = 200
                elif path == "/api/touch":
                    snap = desk_snapshot(app.vault)
                    body = json.dumps(snap.get("touch"), ensure_ascii=False).encode()
                    code, ctype = 200, "application/json; charset=utf-8"
                else:
                    body, code, ctype = b"not-found", 404, "text/plain; charset=utf-8"
                self.send_response(code)
                started = True
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                if path.startswith("/vendor/") and code == 200:
                    self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                if started:
                    return
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"error")
                except Exception:
                    return

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Desk console. No orders.")
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("console binds only to localhost")
    root = Path(args.userdir)
    vault = init_vault(root) if args.init else load_vault(root)
    if not args.serve:
        print(json.dumps(desk_snapshot(vault), ensure_ascii=False, indent=2))
        return 0
    app = ConsoleApp(vault)
    server = ThreadedHTTPServer((args.host, args.port), _handler(app))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
