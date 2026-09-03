"""«Настройки»: ключи и источники — HTML-страница консоли (русский, подсказки).

Секреты показываются маской; пустое поле в форме = «не менять», «удалить» — отдельная
кнопка. Все формы идут на /api/settings и /api/sources с ack_token (localhost only).
Советов на странице нет: только факты и что куда сохраняется.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Any

from capitalizator.ops.settings import FIELDS, SOURCE_KINDS

_KIND_RU = {
    "rss": "RSS-лента (https)",
    "reddit": "Reddit (сабреддит)",
    "x_account": "X / Twitter (аккаунт)",
    "hl_wallet": "Hyperliquid (кошелёк 0x…)",
    "tradingview_own": "TradingView (свой аккаунт)",
}

_CSS = """
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#0e1116;color:#e6e6e6;margin:0;padding:24px;max-width:1100px}
h1{font-size:22px;margin:0 0 6px}h2{font-size:17px;margin:26px 0 8px;color:#9fd3ff}
.note{color:#9aa4b2;font-size:13px}.hint{color:#8b95a5;font-size:12px;margin:2px 0 8px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #222a35;padding:6px 8px;text-align:left;font-size:14px;vertical-align:top}
input,select{background:#151b24;color:#e6e6e6;border:1px solid #2a3442;border-radius:6px;padding:6px 8px;min-width:260px}
button{background:#1f6feb;color:#fff;border:0;border-radius:6px;padding:6px 12px;cursor:pointer}button.warn{background:#7a2e2e}
.set{color:#7ee787}.unset{color:#f0883e}.ack{margin-top:14px;padding:10px;border:1px dashed #3a4452;border-radius:8px}
a{color:#9fd3ff}.card{background:#121821;border:1px solid #1f2a37;border-radius:10px;padding:14px;margin-bottom:14px}
"""


def render_settings_html(
    fields: Sequence[dict[str, Any]], sources: Sequence[dict[str, Any]], *, token: str = ""
) -> str:
    tok = html.escape(token)
    groups: dict[str, list[dict[str, Any]]] = {}
    for f in fields:
        groups.setdefault(str(f["group"]), []).append(f)
    parts: list[str] = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Настройки — Capitalizator</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Настройки: ключи и источники</h1>",
        "<p class='note'>Секреты хранятся только на сервере в <code>secrets/settings.json</code> (права 0600), "
        "в журнал, бэкапы и логи не попадают. Здесь они показаны маской. Пустое поле — «не менять». "
        "Каждое изменение пишет в хеш-цепь только <i>имена</i> полей. <a href='/'>← к столу</a></p>",
    ]
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
        parts.append("</form></div>")
    # sources
    parts.append("<div class='card'><h2>Источники внешней информации</h2>")
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
        "TradingView — только свой аккаунт (sessionid выше).</div></div>"
    )
    parts.append("<p class='note'>Ключи биржи можно задать и без консоли: переменные окружения "
                 "<code>BYBIT_API_KEY / BYBIT_API_SECRET / BYBIT_MODE</code> у процесса signer или файл "
                 "<code>secrets/bybit.json</code> (0600). Эта страница пишет тот же файл.</p>")
    parts.append("</body></html>")
    return "".join(parts)


__all__ = ["render_settings_html", "FIELDS"]
