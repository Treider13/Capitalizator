"""«Управление» — the operator page for everything that used to be API-only.

One server-rendered HTML page (no framework), Russian, every write is a form that
carries the per-process CSRF token and a confirm checkbox and lands on the same JSON
endpoints the scripts use (`/api/command`, `/api/risk`, `/api/universe`). Nothing
here decides anything: the desk and the signer consume the queue on their own tick
and write the result back into `desk_commands`, which the page shows.

Sections: blocked entries + unknown venue positions (ack / release), commands
(flatten / pause / resume / halts / exam / drift release), risk menu (every
`RiskConfig` knob, capped by phase.yaml), sessions (windows, drift flags, budgets,
eligible windows), universe proposal (apply), command log, night / exam / drift facts.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from capitalizator.ops import i18n_ru
from capitalizator.risk.config import STOP_MODES, TRAIL_MODES

CSS = """
body{font-family:system-ui,sans-serif;background:#0f1216;color:#d7dde5;margin:0;padding:16px}
h1{font-size:20px;margin:0 0 8px}h2{font-size:16px;margin:18px 0 6px;color:#9fb3c8}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #263041;padding:4px 6px;text-align:left;vertical-align:top}
th{color:#7f8fa4;font-weight:600}form.inline{display:inline-block;margin:0 6px 6px 0}
input,select{background:#1e2329;color:#d7dde5;border:1px solid #2e3a4d;border-radius:4px;padding:4px 8px}
button{background:#2a3a55;color:#e6edf6;border:1px solid #3d5278;border-radius:4px;padding:4px 10px;cursor:pointer}
button.warn{background:#5a2a2a;border-color:#8a3d3d}.pill{display:inline-block;padding:2px 8px;border-radius:10px;background:#1e2329;margin:0 4px 4px 0;font-size:12px}
.knobs{display:flex;gap:24px;flex-wrap:wrap;margin:8px 0 16px}
.knobs label{display:flex;flex-direction:column;gap:6px;font-size:14px;color:#c5d0dc}
.knobs input{font-size:22px;padding:8px 12px;width:8em;border-color:#4a6a9a}
.ok{color:#6fd18a}.bad{color:#f28b82}.muted{color:#7f8fa4}.hint{font-size:12px;color:#7f8fa4}
label.confirm{font-size:12px;color:#9fb3c8;margin-right:6px}a{color:#8ab4f8}
"""

RISK_HINTS: dict[str, str] = {
    "deposit_share_per_trade": "Доля депозита, которая реально входит в сделку как маржа (10/20/30%). Это размер, не потолок «если влезет».",
    "max_stop_pct": "Максимальный стоп как процент цены (1–5). Система может растянуть стоп до этого; дальше — отказ, не подгонка.",
    "target_risk_pct": "Целевой риск на сделку (доля эквити). Предупреждение в журнале, если получилось больше; сделку не режет. Потолок задаёт phase.yaml.",
    "max_lev": "Максимальное плечо; потолок задаёт phase.yaml.",
    "max_open_positions": "Одновременно открытых идей (по одной на корреляционную группу).",
    "max_intents_per_session": "Потолок заявок на любой ключ бюджета; окна в sessions.yaml режут ниже.",
    "day_halt": "Кран дня: доля эквити (отрицательная), после которой входы закрыты до нового дня.",
    "week_halt": "Кран недели (отрицательная доля).",
    "peak_kill": "Стоп-кран от пика эквити (отрицательная доля); снимает только человек.",
    "fee_multiple_min": "1R должен покрывать столько круговых комиссий (EV-гейт).",
    "stop_mode": "Режим стопа: " + " | ".join(sorted(STOP_MODES)) + ".",
    "manual_stop_frac": "Для manual_bounded: расстояние стопа как доля цены (0.001..0.2) или null.",
    "trail_mode": "Трейл: " + " | ".join(sorted(TRAIL_MODES)) + ".",
    "max_stop_atr": "Стоп не дальше стольких ATR рабочего ТФ; null — без потолка.",
    "participating_share": "Какая доля счёта участвует в размере и кранах (1 — весь).",
    "corr_block_threshold": "Порог корреляции доходностей за 30 дней для запрета второй идеи.",
    "paper_equity": "Эквити бумаги/демо до первого чтения кошелька.",
    "require_ict_marks": "Требовать ICT-метки (OTE/FVG/свип) для входа: true | false.",
    "sentiment_greed": "Месячная жадность (среднее Fear & Greed за 30 дней, ≥20 замеров) от этого порога режет размер (50..100).",
    "sentiment_mult": "Во сколько раз режется размер при месячной жадности (0..1, только вниз).",
    "fragility_thin_z": "Книга «тонкая», когда робастный z глубины у касания ниже этого (отрицательное число).",
}


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _frac_to_pct(value: object) -> str:
    """Stored fraction 0.10 / 0.05 → operator box 10 / 5. Empty if unset."""
    if value in (None, "", "null", "none"):
        return ""
    try:
        return format((Decimal(str(value)) * 100).quantize(Decimal("1")), "f")
    except (InvalidOperation, ValueError, TypeError):
        return ""


def _json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _confirm(token: str, extra_hidden: Mapping[str, str] | None = None) -> str:
    hidden = f"<input type='hidden' name='ack_token' value='{_e(token)}'/>"
    hidden += "<input type='hidden' name='redirect' value='1'/>"
    for key, value in (extra_hidden or {}).items():
        hidden += f"<input type='hidden' name='{_e(key)}' value='{_e(value)}'/>"
    return hidden + "<label class='confirm'><input type='checkbox' name='confirm' required/> подтверждаю</label>"


def _command_form(token: str, kind: str, label: str, *, symbol_input: bool = False,
                  symbol_value: str | None = None, warn: bool = False,
                  select: Sequence[str] | None = None) -> str:
    parts = ["<form class='inline' method='post' action='/api/command'>"]
    hidden = {"kind": kind}
    if symbol_value is not None:
        hidden["symbol"] = symbol_value
    parts.append(_confirm(token, hidden))
    if symbol_input:
        parts.append("<input name='symbol' placeholder='символ или ALL' value='ALL' size='12'/>")
    if select is not None:
        parts.append("<select name='symbol'><option value='ALL'>все окна</option>")
        for name in select:
            parts.append(f"<option value='{_e(name)}'>{_e(name)}</option>")
        parts.append("</select>")
    parts.append("<input name='reason' placeholder='причина (в журнал)' size='18'/>")
    parts.append(f"<button type='submit'{' class=\"warn\"' if warn else ''}>{_e(label)}</button></form>")
    return "".join(parts)


def render_ops_html(
    *,
    token: str,
    status: Mapping[str, Any],
    risk: Mapping[str, Any],
    sessions: Mapping[str, Any],
    universe: Mapping[str, Any],
    commands: Sequence[Mapping[str, Any]],
    meta: Mapping[str, str | None],
    message: str | None = None,
) -> str:
    exch = _json(meta.get("exchange_state"), {}) or {}
    blocked = list(status.get("entries_blocked") or [])
    since = _json(meta.get("entries_blocked_since"), {}) or {}
    unknown = list(exch.get("unknown_detail") or [])
    stop_missing = list(exch.get("stop_missing") or [])
    mismatches = list(exch.get("mismatches") or [])
    acct = (status.get("money") or {}).get("account") or {}
    paused = meta.get("entries_paused") == "1"
    window_drift = _json(meta.get("window_drift"), {}) or {}
    drift = _json(meta.get("drift"), {}) or {}
    exam_last = _json(meta.get("exam_last"), {}) or {}
    night = _json(meta.get("night_last"), {}) or {}
    champion = _json(meta.get("champion_candidate"), {}) or {}

    out: list[str] = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<title>Управление — Capitalizator</title>"
        f"<style>{CSS}</style></head><body>",
        "<h1>Управление</h1>",
        "<p class='hint'><a href='/'>← Стол</a> · <a href='/settings'>Настройки: ключи и источники</a>"
        " · <a href='/api/glossary'>Словарь кодов</a> · <a href='/api/sessions'>сессии (JSON)</a>"
        " · <a href='/api/commands'>журнал команд (JSON)</a></p>",
    ]
    if message:
        out.append(f"<p class='pill ok'>{_e(message)}</p>")

    # --- entries / venue truth -----------------------------------------------------------
    out.append("<h2>Входы и правда биржи</h2>")
    if blocked:
        items = "".join(
            f"<li><b>{_e(i18n_ru.ru(b))}</b> <span class='muted'>({_e(b)}"
            + (f", с {_e(since.get(b))}" if since.get(b) else "")
            + f")</span> — {_e(i18n_ru.hint(b))}</li>"
            for b in blocked
        )
        out.append(f"<p class='bad'>Входы заблокированы:</p><ul>{items}</ul>")
    else:
        out.append("<p class='ok'>Входы не заблокированы.</p>")
    if unknown:
        unknown_rows = "".join(
            f"<tr><td>{_e(u.get('symbol'))}</td><td>{_e(u.get('side'))}</td><td>{_e(u.get('size'))}</td>"
            f"<td>{_e(u.get('avg_price'))}</td><td>{_e(u.get('stop_loss') or '—')}</td>"
            f"<td>{_command_form(token, 'ack_position', 'Принять позицию', symbol_value=str(u.get('symbol')))}</td></tr>"
            for u in unknown
        )
        out.append(
            "<p class='bad'>Позиции на бирже, которых стол не открывал (усыновление только руками):</p>"
            "<table><tr><th>символ</th><th>сторона</th><th>размер</th><th>средняя</th><th>стоп</th><th></th></tr>"
            f"{unknown_rows}</table>"
        )
    if stop_missing:
        out.append(f"<p class='bad'>Без подтверждённого стопа на бирже: {_e(', '.join(stop_missing))}</p>")
    if mismatches:
        out.append(
            "<p class='bad'>Расхождения WS/REST: "
            + _e("; ".join(f"{m.get('symbol')}:{m.get('field')} ws={m.get('ws')} rest={m.get('rest')}" for m in mismatches))
            + "</p>"
        )
    out.append(
        "<p>"
        + _command_form(token, "release_signer", "Снять блок сигнера", warn=True)
        + "<span class='hint'>Сначала «Принять позицию» для каждой чужой позиции — иначе блок вернётся на следующей сверке.</span></p>"
    )

    # --- commands ------------------------------------------------------------------------
    out.append("<h2>Команды столу</h2>")
    halt = acct.get("halt_reason") or ""
    out.append(
        f"<p>Кран: <b class='{'bad' if halt else 'ok'}'>{_e(halt or 'открыт')}</b> · "
        f"входы на паузе: <b>{'да' if paused else 'нет'}</b> · "
        f"режим оператора: <b>{_e(status.get('user_mode'))}</b> · режим фазы (phase.yaml): "
        f"<b>{_e(status.get('trading_mode'))}</b> · контур: <b>{_e(status.get('contour'))}</b></p>"
    )
    out.append(
        "<p>"
        + _command_form(token, "flatten", "Закрыть позиции", symbol_input=True, warn=True)
        + _command_form(token, "pause_entries", "Пауза входов")
        + _command_form(token, "resume_entries", "Возобновить входы")
        + _command_form(token, "release_halts", "Снять кран (после недели/пика/ликвидации)", warn=True)
        + "</p><p>"
        + _command_form(token, "promote", "Экзамен претендента (отчёт, без переключения)")
        + _command_form(token, "drift_release", "Снять дрейф окна", select=sorted(window_drift))
        + "</p>"
    )

    # --- risk menu -----------------------------------------------------------------------
    out.append("<h2>Риск-меню</h2>")
    cfg = dict(risk.get("risk_config") or {})
    out.append(
        f"<p class='hint'>Версия {_e(cfg.get('version'))}, id {_e(cfg.get('config_id'))}. "
        "Пустое поле — без изменений. Потолки риска и плеча берутся из phase.yaml и не поднимаются отсюда.</p>"
    )
    out.append("<form method='post' action='/api/risk'>" + _confirm(token))
    share_pct = _frac_to_pct(cfg.get("deposit_share_per_trade"))
    stop_pct = _frac_to_pct(cfg.get("max_stop_pct"))
    out.append(
        "<h3>Сделка: доля депозита и максимальный стоп</h3>"
        "<p class='hint'>Два обязательных окна. Доля депозита — сколько маржи реально "
        "входит в сделку. Стоп система может растянуть до указанного процента цены; "
        "дальше — отказ. Если получившийся риск больше целевого — сделка ставится, "
        "в журнале предупреждение (кран дня/недели по-прежнему срабатывает после убытка).</p>"
        "<div class='knobs'>"
        "<label>Доля депозита в сделку, %"
        f"<input id='knob-deposit-share' name='deposit_share_per_trade' "
        f"inputmode='decimal' size='6' value='{_e(share_pct)}'/></label>"
        "<label>Максимальный стоп, %"
        f"<input id='knob-max-stop' name='max_stop_pct' "
        f"inputmode='decimal' size='6' value='{_e(stop_pct)}'/></label>"
        "</div>"
    )
    out.append("<table>")
    out.append("<tr><th>параметр</th><th>сейчас</th><th>новое</th><th>что это</th></tr>")
    for key, value in cfg.items():
        if key in {"version", "config_id", "deposit_share_per_trade", "max_stop_pct"}:
            continue
        out.append(
            f"<tr><td><code>{_e(key)}</code></td><td>{_e(value)}</td>"
            f"<td><input name='{_e(key)}' size='10' placeholder='{_e(value)}'/></td>"
            f"<td class='hint'>{_e(RISK_HINTS.get(key, ''))}</td></tr>"
        )
    out.append("</table><button type='submit'>Сохранить риск-меню</button></form>")

    # --- sessions ------------------------------------------------------------------------
    out.append("<h2>Сессии (infra/sessions.yaml)</h2>")
    now = sessions.get("now") or {}
    out.append(
        f"<p>Сейчас окно <b>{_e(now.get('window'))}</b>"
        + (" (выходные)" if now.get("weekend") else "")
        + f" · размер ×{_e(now.get('size_mult'))} · k·ATR {_e(now.get('k_atr'))} · бюджет {_e(now.get('budget'))}"
        + f" · потолок заявок за будний день по всем окнам: {_e(sessions.get('daily_budget_cap', '—'))}"
        + (f" · блэкауты: {_e(', '.join(now.get('blackouts') or []))}" if now.get("blackouts") else "")
        + "</p>"
    )
    spent = sessions.get("budget_spent_today") or {}
    eligible = sessions.get("eligible_windows") or {}
    k_atr_cal = sessions.get("k_atr_calibrated") or {}
    win_rows: list[str] = []
    for w in sessions.get("windows") or []:
        name = str(w.get("name"))
        flags = []
        if w.get("closed"):
            flags.append("закрыто")
        if name in window_drift:
            flags.append(f"дрейф с {window_drift[name]}")
        if name in eligible:
            flags.append("готово к открытию (нижняя граница > безубытка)")
        win_rows.append(
            f"<tr><td>{_e(name)}</td><td>{_e(w.get('start') or '—')}–{_e(w.get('end') or '—')}</td>"
            f"<td>{_e(', '.join(w.get('ideas') or []) or '—')}</td><td>×{_e(w.get('size_mult'))}</td>"
            f"<td>{_e(w.get('k_atr'))}"
            + (f" → {_e(k_atr_cal.get(name))} (по MAE)" if k_atr_cal.get(name) else "")
            + f"</td><td>{_e(spent.get(name, 0))}/{_e(w.get('budget'))}</td>"
            f"<td class='{'bad' if flags else 'ok'}'>{_e('; '.join(flags) or 'открыто')}</td></tr>"
        )
    out.append(
        "<table><tr><th>окно</th><th>UTC</th><th>идеи</th><th>размер</th><th>k·ATR</th>"
        "<th>заявок сегодня</th><th>состояние</th></tr>" + "".join(win_rows) + "</table>"
    )
    out.append(
        f"<p class='hint'>Дрейф чемпиона (весь стол): {'есть' if drift.get('drift') else 'нет'}"
        f" (n={_e(drift.get('n', 0))}, целевой риск {_e(drift.get('target_risk', '—'))}). "
        "Дрейф окна режет размер этого окна вдвое до команды «Снять дрейф окна»; дрейф чемпиона "
        "режет целевой риск всего стола и снимается сам, когда серия ошибок выравнивается.</p>"
    )

    # --- universe ------------------------------------------------------------------------
    out.append("<h2>Вселенная символов</h2>")
    out.append(f"<p>Сейчас: {_e(', '.join(universe.get('current') or []))}</p>")
    proposal = universe.get("proposal") or {}
    if proposal:
        pid = str(proposal.get("proposal_id") or proposal.get("id") or "")
        symbols = proposal.get("symbols") or proposal.get("universe") or []
        out.append(
            f"<p>Предложение сигнера от {_e(proposal.get('at') or proposal.get('ranked_at'))}: "
            f"{_e(', '.join(str(s) for s in symbols))}</p>"
            "<form class='inline' method='post' action='/api/universe'>"
            + _confirm(token, {"proposal_id": pid})
            + "<button type='submit'>Применить предложение (сразу, без рестарта)</button></form>"
        )
    else:
        out.append("<p class='muted'>Предложения нет: сигнер публикует и применяет его ежедневно (топ-10, гистерезис), когда есть ключ и тикеры.</p>")
    if universe.get("proposal_error"):
        out.append(f"<p class='bad'>Ошибка предложения: {_e(universe.get('proposal_error'))}</p>")
    applied = universe.get("applied") or {}
    if applied:
        out.append(f"<p class='hint'>Последнее применение: {_e(json.dumps(applied, ensure_ascii=False)[:300])}</p>")

    # --- learning facts -------------------------------------------------------------------
    out.append("<h2>Ночь, экзамен, чемпион</h2>")
    out.append(
        f"<p>Ночной отчёт: {_e(night.get('day') or '—')}"
        + (f" (строк {_e(night.get('n_rows'))}, тень {_e(night.get('n_shadow'))}, классов {_e(night.get('classes'))})" if night else "")
        + f" · экзамен: {'пройден' if exam_last.get('passed') else 'не пройден / не проводился'}"
        + (f" ({_e(exam_last.get('at'))})" if exam_last.get("at") else "")
        + (f" · кандидат в чемпионы с {_e(champion.get('since'))} — переключение только через код-ревью" if champion else "")
        + "</p>"
    )

    # --- process health --------------------------------------------------------------------
    out.append("<h2>Здоровье процессов</h2>")

    def _age(key: str) -> str:
        raw = meta.get(key)
        if not raw:
            return "нет"
        try:
            from datetime import UTC, datetime

            at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return f"{(datetime.now(tz=UTC) - at).total_seconds():.0f} с назад"
        except ValueError:
            return _e(raw)

    dead_man = _json(meta.get("dead_man_last"), {}) or {}
    intel_status = _json(meta.get("intel_status"), {}) or {}
    rec_status = _json(meta.get("recorder_status"), {}) or {}
    rec_streams = rec_status.get("streams") or {}
    health_rows: list[tuple[str, str]] = [
        ("пульс стола", _age("desk_heartbeat")),
        ("пульс сигнера", _age("signer_heartbeat")),
        ("стол догоняет ленту", "да" if meta.get("desk_backlog") == "1" else "нет"),
        ("рекордер: сокет", "подключён" if rec_status.get("socket_connected") else _e(rec_status.get("socket_connected"))),
        ("рекордер: реконнектов", _e(rec_status.get("reconnects", "—"))),
        ("рекордер: возраст последнего кадра trades", _e((rec_streams.get("trades") or {}).get("last_age_s", "—"))),
        ("сторож: последнее срабатывание", _e(json.dumps(dead_man, ensure_ascii=False)) if dead_man else "не срабатывал"),
        ("интенты, возвращённые после появления ключа", _e(meta.get("signer_requeued") or "0")),
        ("инструменты: ошибка сигнера / рекордера", f"{_e(meta.get('instruments_error_signer') or '—')} / {_e(meta.get('instruments_error_recorder') or '—')}"),
        ("intel: последний цикл", _e(intel_status.get("at") or "—")),
        ("intel: источников / сохранено", f"{_e((intel_status.get('fetch') or {}).get('sources', '—'))} / {_e((intel_status.get('fetch') or {}).get('stored', '—'))}"),
        ("intel: ошибка LLM / Reddit", f"{_e(meta.get('llm_last_error') or '—')} / {_e(meta.get('reddit_auth_error') or '—')}"),
        ("двойники после рестарта", f"восстановлено {_e(meta.get('paper_restored') or '0')}, ошибка: {_e(meta.get('paper_open_error') or '—')}"),
        ("ОКО: органы, не прочитанные при старте", _e(", ".join(sorted(_json(meta.get("oko_load_errors"), {}) or {})) or "нет")),
    ]
    out.append(
        "<table>" + "".join(f"<tr><th>{_e(k)}</th><td>{v}</td></tr>" for k, v in health_rows) + "</table>"
    )

    # --- command log ----------------------------------------------------------------------
    out.append("<h2>Журнал команд</h2>")
    log_rows: list[str] = []
    for c in list(commands)[:40]:
        payload = c.get("payload") or {}
        result = c.get("result")
        log_rows.append(
            f"<tr><td>{_e(c.get('created_ts'))}</td><td>{_e(i18n_ru.ru(str(c.get('kind'))))}</td>"
            f"<td>{_e(payload.get('symbol') or '')}</td><td>{_e(payload.get('reason') or '')}</td>"
            f"<td class='{'ok' if c.get('status') == 'done' else ('bad' if c.get('status') == 'failed' else 'muted')}'>{_e(c.get('status'))}</td>"
            f"<td class='hint'>{_e(json.dumps(result, ensure_ascii=False, default=str)[:200] if result else '')}</td></tr>"
        )
    out.append(
        "<table><tr><th>когда</th><th>команда</th><th>символ/окно</th><th>причина</th><th>статус</th><th>результат</th></tr>"
        + ("".join(log_rows) or "<tr><td colspan='6' class='muted'>команд не было</td></tr>")
        + "</table>"
    )
    out.append("</body></html>")
    return "".join(out)
