"""«Настройки»: ключи и источники — HTML-страница консоли (русский, подсказки).

Секреты показываются маской; пустое поле в форме = «не менять», «удалить» — отдельная
кнопка. Все формы идут на /api/settings и /api/sources с ack_token (localhost only).
Советов на странице нет: только факты и что куда сохраняется.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Any

from capitalizator.ops.desk_chrome import chrome_end, chrome_start
from capitalizator.ops.settings import FIELDS, SOURCE_KINDS

_KIND_RU = {
    "rss": "RSS-лента (https)",
    "reddit": "Reddit (сабреддит)",
    "x_account": "X / Twitter (аккаунт)",
    "hl_wallet": "Hyperliquid (кошелёк 0x…)",
    "tradingview_own": "TradingView (свой аккаунт)",
}


def render_settings_html(
    fields: Sequence[dict[str, Any]],
    sources: Sequence[dict[str, Any]],
    *,
    token: str = "",
    message: str | None = None,
) -> str:
    tok = html.escape(token)
    groups: dict[str, list[dict[str, Any]]] = {}
    for f in fields:
        groups.setdefault(str(f["group"]), []).append(f)
    extra = ".set{color:#7ee787}.unset{color:#f0883e}.ack{margin-top:14px;padding:10px;border:1px dashed #3a4452}"
    parts: list[str] = [
        chrome_start(title="Настройки — ХРОНОС", active="settings", extra_css=extra),
        "<div class='page-body'>",
        "<h1>Настройки: ключи и источники</h1>",
        "<p class='note'>Секреты хранятся только на сервере в <code>secrets/settings.json</code> (права 0600), "
        "в журнал, бэкапы и логи не попадают. Здесь они показаны маской. Пустое поле — «не менять». "
        "Каждое изменение пишет в хеш-цепь только <i>имена</i> полей.</p>",
    ]
    if message:
        parts.append(f"<p class='pill ok'><b>{html.escape(message)}</b></p>")
    parts.append("<div class='set-grid'><section class='panel'><h2>Как включить стол — 3 шага</h2>")
    parts.append(
        "<ol class='wizard'>"
        "<li><b>Шаг 1. Ключ</b> — файл <code>secrets/bybit.json</code>, права 0600. "
        "Секрет в журнал не возвращается."
        "<form method='post' action='/api/settings'>"
        "<input type='hidden' name='redirect' value='1'/>"
        f"<input type='hidden' name='ack_token' value='{tok}'/>"
        "<input type='text' name='bybit.api_key' placeholder='API-ключ' autocomplete='off' spellcheck='false'/>"
        "<input type='password' name='bybit.api_secret' placeholder='секрет' autocomplete='off'/>"
        "<select name='bybit.mode'>"
        "<option value='demo' selected>учебный счёт Bybit Demo</option>"
        "<option value='testnet'>testnet</option>"
        "<option value='live_sub'>live сабаккаунт</option>"
        "<option value='live_main'>live основной</option></select>"
        "<label class='confirm'><input type='checkbox' name='confirm' required/> Подтверждаю: понимаю, что меняю</label> "
        "<button type='submit'>1. Сохранить ключ</button></form></li>"
        "<li><b>Шаг 2. Hello</b> — проверка ключа на бирже. Не галочка в журнале."
        "<form method='post' action='/api/hello'>"
        f"<input type='hidden' name='ack_token' value='{tok}'/>"
        "<input type='hidden' name='redirect' value='1'/>"
        "<button type='submit'>2. Проверить ключ на бирже</button></form></li>"
        "<li><b>Шаг 3. Режим</b> — чемпион сам не повышается. Кнопка ордер не рисует. "
        "Вход только при ACCORD и открытом окне."
        "<form method='post' action='/mode'>"
        f"<input type='hidden' name='ack_token' value='{tok}'/>"
        "<button type='submit' name='mode' value='off'>off</button>"
        "<button type='submit' name='mode' value='learn'>learn</button>"
        "<button type='submit' name='mode' value='demo'>demo</button>"
        "<button type='submit' name='mode' value='live'>live</button>"
        "<input name='override_reason' placeholder='причина live, если гейт не пройден (≥ 8 знаков)' size='36'/>"
        "</form></li></ol></section><div class='stack'>"
    )
    for group, rows in groups.items():
        parts.append(f"<div class='card'><h2>{html.escape(group)}</h2>")
        parts.append("<form method='post' action='/api/settings'><input type='hidden' name='redirect' value='1'/>")
        parts.append("<table><thead><tr><th>Поле</th><th>Сейчас</th><th>Новое значение</th></tr></thead><tbody>")
        for f in rows:
            key = html.escape(str(f["key"]))
            state = (
                f"<span class='set'>задано: {html.escape(str(f['display']))}</span>"
                if f["set"]
                else "<span class='unset'>не задано</span>"
            )
            itype = "password" if f["secret"] else "text"
            parts.append(
                "<tr>"
                f"<td><b>{html.escape(str(f['label']))}</b><div class='hint'>{html.escape(str(f['hint']))}</div>"
                f"<div class='hint'><code>{key}</code></div></td>"
                f"<td>{state}</td>"
                f"<td><input type='{itype}' name='{key}' autocomplete='off' placeholder='оставить как есть'/></td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        parts.append(
            f"<div class='ack'><input type='hidden' name='ack_token' value='{tok}'/>"
            "<label><input type='checkbox' name='confirm' required/> Подтверждаю: понимаю, что меняю</label> "
            "<button type='submit'>Сохранить группу</button></div>"
        )
        if group == "Оповещения":
            parts.append(
                "</form><form method='post' action='/api/alerts/test' class='inline'>"
                f"<input type='hidden' name='ack_token' value='{tok}'/>"
                "<input type='hidden' name='redirect' value='1'/>"
                "<button type='submit'>Проверить Telegram (тестовое сообщение)</button>"
            )
        parts.append("</form></div>")
    parts.append("</div><section class='panel'>")
    parts.append("<h2>Источники внешней информации</h2>")
    parts.append(
        "<p class='note'>Внешняя информация — только фильтр риска, метка карточки и один голос жюри. "
        "Никогда не вход и не размер. Telegram и скрейпинг как источники запрещены каноном.</p>"
    )
    parts.append("<table><thead><tr><th>Тип</th><th>Значение</th><th>Метка</th><th>Вкл</th><th>Последний успех</th><th>Ошибка</th><th></th></tr></thead><tbody>")
    if not sources:
        parts.append("<tr><td colspan='7' class='note'>источников нет — добавьте ниже</td></tr>")
    for src in sources:
        sid = html.escape(str(src.get("id")))
        enabled = bool(src.get("enabled"))
        toggle = "disable" if enabled else "enable"
        parts.append(
            "<tr>"
            f"<td>{html.escape(_KIND_RU.get(str(src.get('kind')), str(src.get('kind'))))}</td>"
            f"<td><code>{html.escape(str(src.get('value')))}</code></td>"
            f"<td>{html.escape(str(src.get('label') or ''))}</td>"
            f"<td>{'да' if enabled else 'нет'}</td>"
            f"<td>{html.escape(str(src.get('last_ok') or '—'))}</td>"
            f"<td>{html.escape(str(src.get('last_error') or ''))}</td>"
            "<td>"
            f"<form method='post' action='/api/sources' style='display:inline'><input type='hidden' name='redirect' value='1'/>"
            f"<input type='hidden' name='action' value='{toggle}'/><input type='hidden' name='id' value='{sid}'/>"
            f"<input type='hidden' name='ack_token' value='{tok}'/><button type='submit'>{'выключить' if enabled else 'включить'}</button></form> "
            f"<form method='post' action='/api/sources' style='display:inline'><input type='hidden' name='redirect' value='1'/>"
            f"<input type='hidden' name='action' value='remove'/><input type='hidden' name='id' value='{sid}'/>"
            f"<input type='hidden' name='ack_token' value='{tok}'/><button type='submit' class='warn'>удалить</button></form>"
            "</td></tr>"
        )
    parts.append("</tbody></table>")
    options = "".join(
        f"<option value='{k}'>{html.escape(_KIND_RU.get(k, k))}</option>" for k in SOURCE_KINDS
    )
    parts.append(
        "<h2>Добавить источник</h2>"
        "<form method='post' action='/api/sources'><input type='hidden' name='redirect' value='1'/>"
        "<input type='hidden' name='action' value='add'/>"
        f"<select name='kind'>{options}</select> "
        "<input name='value' placeholder='https://… | сабреддит | @аккаунт | 0x…' required/> "
        "<input name='label' placeholder='метка (необязательно)'/> "
        f"<input type='hidden' name='ack_token' value='{tok}'/> "
        "<button type='submit'>Добавить</button></form>"
        "<div class='hint'>RSS — только https. Reddit — имя сабреддита без r/. X — имя аккаунта; читается через официальный API "
        "(нужен bearer выше). Hyperliquid — адрес кошелька; учитывается только когорта, не один кит. "
        "TradingView — только свой аккаунт (sessionid выше).</div></section></div>"
    )
    parts.append("<p class='note'>Ключи биржи можно задать и без консоли: переменные из "
                 "<code>.env.example</code> у процесса signer или файл "
                 "<code>secrets/bybit.json</code> (0600). Эта страница пишет тот же файл.</p>"
                 "</div>")
    parts.append(chrome_end())
    return "".join(parts)


__all__ = ["render_settings_html", "FIELDS"]
