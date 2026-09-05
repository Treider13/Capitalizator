"""Shared Tape Desk chrome: CSS, tab bar, glossary HTML. No orders. No advice."""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import quote

from capitalizator.ops import i18n_ru
from capitalizator.ops.daily_map_report import contains_advice

DESK_CSS = """
:root{
  --bg:#07090d;--panel:#0c1014;--panel2:#10161c;--line:#1a222c;--line2:#243040;
  --text:#e8eef2;--muted:#7d8b99;--bid:#00c853;--ask:#ff3b4e;--gold:#e6a817;
  --teal:#5eead4;--warn:#f0b90b;--fill:#141c26;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);
  font:12px/1.4 ui-sans-serif,system-ui,sans-serif}
body.desk-app{min-height:100vh;display:flex;flex-direction:column}
body.desk-app .desk-grid{flex:1 1 auto}
a{color:var(--teal);text-decoration:none}
a:hover{text-decoration:underline}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px}
.topbar{
  display:flex;flex-direction:column;gap:0;padding:0;
  border-bottom:1px solid var(--line);background:#090d12;
  position:sticky;top:0;z-index:20
}
.topbar-row{
  display:flex;flex-wrap:wrap;gap:8px;align-items:center;
  padding:5px 10px;border-bottom:1px solid var(--line)
}
.topbar-row:last-child{border-bottom:0}
.brand{font-weight:700;letter-spacing:.14em;font-size:14px}
.sub{color:var(--muted);letter-spacing:.08em;font-size:11px;text-transform:uppercase}
.tabs{display:flex;gap:0;margin-left:8px}
.tabs a{
  color:var(--muted);padding:6px 12px;border-bottom:2px solid transparent;text-decoration:none
}
.tabs a.on{color:var(--teal);border-bottom-color:var(--teal)}
.pill,.status-lock{
  border:1px solid var(--line);padding:2px 8px;color:var(--muted);font-size:11px;
  font-family:ui-monospace,Menlo,Consolas,monospace
}
.pill.ok{color:var(--bid);border-color:#00c85355}
.pill.bad{color:var(--ask);border-color:#ff3b4e55}
.pill.warn{color:var(--warn);border-color:#f0b90b55}
.status-lock{color:#9aa7b5;cursor:default}
.gates{display:flex;gap:4px;flex-wrap:wrap}
.gate{
  min-width:42px;text-align:center;padding:3px 6px;border:1px solid var(--line);
  font:11px/1.2 ui-monospace,Menlo,Consolas,monospace
}
.gate.green{color:var(--bid);border-color:#00c85355}
.gate.red{color:var(--ask);border-color:#ff3b4e55}
button,select,input,textarea{
  background:#151c24;color:var(--text);border:1px solid var(--line2);
  padding:4px 8px;font:12px/1.3 inherit
}
button{cursor:pointer;color:var(--text)}
button:hover:not(:disabled){border-color:var(--teal);color:#fff}
button:disabled,.dead{opacity:.45;cursor:not-allowed}
button.warn,button.danger{background:#3a1518;border-color:#8a3d3d;color:#ffb4b4}
button.mode.on{color:var(--bid);border-color:#00c85399;background:#0d2418}
button.tf.on{color:var(--teal);border-color:#5eead466}
.page{padding:8px;flex:1}
.panel,.card{
  background:var(--panel);border:1px solid var(--line);padding:8px 10px
}
.panel h2,h2{
  margin:0 0 6px;font-size:11px;color:var(--muted);font-weight:600;
  letter-spacing:.08em;text-transform:uppercase
}
h1{margin:0;font-size:16px;letter-spacing:.08em}
.empty,.muted,.hint,.note{color:var(--muted)}
.hint,.note{font-size:12px}
.ok{color:var(--bid)}.bad{color:var(--ask)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:3px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}
.num,td.bid,td.ask,.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.bid{color:var(--bid)}.ask{color:var(--ask)}
.strip{margin:0;padding:4px 10px;border-bottom:1px solid var(--line);background:var(--panel)}
.strip details{margin:0}
.strip summary{cursor:pointer;color:var(--muted);font-size:11px;letter-spacing:.06em;text-transform:uppercase}
.desk-grid{
  display:grid;grid-template-columns:260px minmax(0,1.7fr) 340px;
  grid-template-rows:minmax(360px,1fr);gap:6px;padding:6px;flex:1;min-height:0
}
@media (max-width:1100px){.desk-grid{grid-template-columns:1fr}}
.chart-panel{display:flex;flex-direction:column;min-width:0}
.chart-host{position:relative;flex:1;min-height:320px;background:#080c10}
#tv-chart{position:absolute;inset:0;width:100%;height:100%}
.chart-panel canvas#chart{width:100%;height:100%;min-height:320px;background:#080c10;flex:1}
.chart-host.engine-tv canvas#chart{display:none}
.chart-host.engine-canvas #tv-chart{display:none}
.book-host{position:relative;flex:1;min-height:0}
.book-panel{display:flex;flex-direction:column;min-height:0}
.book-gpu{display:none;width:100%;min-height:320px}
.book-host.gpu .book-gpu{display:block}
.book-host.gpu #book{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
.right-col,.col{display:flex;flex-direction:column;gap:6px;min-width:0}
.bottom-grid{
  display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;padding:0 6px 6px
}
@media (max-width:900px){.bottom-grid{grid-template-columns:1fr}}
.ladder{font:11px/1.35 ui-monospace,Menlo,Consolas,monospace;max-height:52vh;overflow:auto}
.ladder .row{display:grid;grid-template-columns:1fr 72px 1fr;align-items:center;position:relative}
.ladder .bar{position:absolute;top:1px;bottom:1px;opacity:.28}
.ladder .bar.ask{background:var(--ask);right:0}
.ladder .bar.bid{background:var(--bid);left:0}
.ladder .mid{
  grid-column:1/-1;text-align:center;padding:4px 0;color:#fff;font-size:16px;font-weight:700
}
.imbalance{display:flex;height:8px;margin-top:6px;background:#1a1515}
.imbalance[hidden]{display:none!important}
.imbalance i{display:block;height:100%;background:var(--bid)}
.imbalance b{display:block;height:100%;background:var(--ask);flex:1}
.why{display:flex;flex-direction:column;gap:4px}
.why article{
  display:grid;grid-template-columns:92px 1fr;gap:6px;border:1px solid var(--line);
  padding:4px 6px;font-size:11px
}
.why b{color:var(--muted);font-size:10px;letter-spacing:.06em}
.replay{
  display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px;color:var(--muted)
}
.replay input[type=range]{flex:1;min-width:120px}
.ops-grid,.set-grid{
  display:grid;grid-template-columns:1fr 1.35fr 1fr;gap:8px;align-items:start
}
@media (max-width:1100px){.ops-grid,.set-grid{grid-template-columns:1fr}}
.cmd-wrap{display:flex;flex-wrap:wrap;gap:8px}
form.inline{display:inline-flex;flex-wrap:wrap;gap:6px;align-items:center;
  border:1px solid var(--line);padding:6px;background:var(--panel2)}
.knobs{display:flex;gap:24px;flex-wrap:wrap;margin:8px 0}
.knobs label{display:flex;flex-direction:column;gap:6px;font-size:13px;color:#c5d0dc}
.knobs input{font-size:22px;padding:8px 12px;width:8em;border-color:#4a6a9a}
label.confirm{font-size:12px;color:#9fb3c8}
.page-body{padding:10px}
.stack{display:flex;flex-direction:column;gap:8px}
.gloss{display:grid;grid-template-columns:180px 1fr 280px;gap:8px;min-height:70vh}
@media (max-width:1000px){.gloss{grid-template-columns:1fr}}
.filters{display:flex;flex-direction:column;gap:4px}
.filters a{
  color:var(--muted);border:1px solid var(--line);padding:4px 8px;background:#151c24
}
.filters a.on{color:var(--gold);border-color:#e6a81766}
.term-row{cursor:pointer}
.term-row.on{background:#2a2210}
.inspect h2{color:var(--gold);font-size:22px;letter-spacing:.12em;text-transform:none}
.touch-grid{display:grid;grid-template-columns:1.1fr 1.2fr .9fr;gap:8px}
@media (max-width:1000px){.touch-grid{grid-template-columns:1fr}}
pre.flight{font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap}
.plus{color:var(--bid)}.minus{color:var(--ask)}
#service{margin:0 6px 8px;padding:8px 10px;border:1px solid var(--line);background:var(--panel)}
#service h2{margin-top:12px}
footer{padding:8px 12px 16px;color:var(--muted);font-size:11px}
.wizard li{margin:8px 0}
"""

_TABS = (
    ("stol", "/", "Стол"),
    ("ops", "/ops", "Управление"),
    ("settings", "/settings", "Настройки"),
    ("touch", "/touch", "Касание"),
    ("glossary", "/glossary", "Словарь"),
)

GLOSSARY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ЖЮРИ", ("ACCORD", "SPLIT", "VETO", "SILENCE")),
    ("CAV", ("REJECT", "THROUGH", "COMPRESS", "DRIFT", "NOISE")),
    ("ZLG", ("DEFEND", "RETREAT", "IMPROVE", "FADE")),
    ("ОКО", ("CLEAN", "SPOOF", "LAYERING", "CASCADE", "THIN", "UNKNOWN",
             "BUILD_LONG", "BUILD_SHORT", "UNWIND", "ICEBERG", "ABSORB", "SWEEP", "NONE")),
    ("ПОГОДА", ("RANGE", "TREND", "TRANSITION", "VOL_EXPANSION")),
    ("ИСХОДы", ("bounce", "break", "die", "pending")),
    ("ИДЕИ", ("spring", "breakout", "fade_spring")),
    ("БЛОКи сигнера", ("no_gateway", "reconcile_mismatch", "desk", "ws_private", "rest",
                      "clock", "mode_mismatch", "unknown_position", "stop_missing",
                      "sl_unconfirmed", "sl_retry")),
    ("КОМАНДы", ("flatten", "pause_entries", "resume_entries", "release_halts",
                "release_signer", "ack_position", "promote", "drift_release")),
    ("ИНТЕНТы", ("sent", "rejected", "unknown", "failed", "skipped", "pending_intent")),
    ("РЕЖИМы", ("off", "learn", "demo", "live", "testnet", "live_sub", "live_main")),
)


def nav_html(active: str) -> str:
    parts = ['<nav class="tabs">']
    for key, href, label in _TABS:
        cls = " on" if key == active else ""
        parts.append(f'<a class="{cls.strip()}" href="{href}">{html.escape(label)}</a>')
    parts.append("</nav>")
    return "".join(parts)


def chrome_start(*, title: str, active: str, extra_css: str = "") -> str:
    return (
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        f"<title>{html.escape(title)}</title>"
        f"<style>{DESK_CSS}{extra_css}</style></head><body class='desk-app'>"
        "<header class='topbar'><div class='topbar-row'><div class='brand'>ХРОНОС</div>"
        "<span class='sub'>Tape Desk</span>"
        f"{nav_html(active)}</div></header>"
    )


def chrome_end() -> str:
    return (
        "<footer>Стол. Торги с консоли нельзя. Сделок нет, пока нет ленты. "
        "Ключи сюда не попадают.</footer></body></html>"
    )


def _group_of(code: str) -> str:
    for name, codes in GLOSSARY_GROUPS:
        if code in codes:
            return name
    return "прочее"


def render_glossary_html(*, q: str = "", group: str = "") -> str:
    terms = i18n_ru.glossary()
    counts: dict[str, int] = {}
    for row in terms:
        counts[_group_of(str(row["code"]))] = counts.get(_group_of(str(row["code"])), 0) + 1
    qn = q.strip().lower()
    shown = []
    for row in terms:
        blob = f"{row['code']} {row['name']} {row['hint']}".lower()
        gname = _group_of(str(row["code"]))
        if group and gname != group:
            continue
        if qn and qn not in blob:
            continue
        shown.append(row)
    filters = [f'<a class="{"on" if not group else ""}" href="/glossary">все {len(terms)}</a>']
    for name, _codes in GLOSSARY_GROUPS:
        cls = "on" if group == name else ""
        href = "/glossary?group=" + quote(name)
        if qn:
            href += "&q=" + quote(q)
        filters.append(
            f'<a class="{cls}" href="{href}">{html.escape(name)} {counts.get(name, 0)}</a>'
        )
    rows_html = []
    first = shown[0]["code"] if shown else ""
    for row in shown:
        code = str(row["code"])
        rows_html.append(
            "<tr class='term-row' data-code='"
            + html.escape(code)
            + "'>"
            f"<td class='mono'>{html.escape(code)}</td>"
            f"<td>{html.escape(str(row['name']))}</td>"
            f"<td class='hint'>{html.escape(str(row['hint']))}</td></tr>"
        )
    inspect = "<p class='empty'>выберите код</p>"
    if shown:
        hit = shown[0]
        inspect = (
            f"<p class='mono'>{html.escape(str(hit['code']))}</p>"
            f"<h2>{html.escape(str(hit['name']))}</h2>"
            f"<p>{html.escape(str(hit['hint']))}</p>"
            "<p class='hint'>коды в журнале английские — сравнимость и хеш-цепь</p>"
        )
    page = (
        chrome_start(title="Словарь — ХРОНОС", active="glossary")
        + "<div class='page-body gloss'>"
        "<aside class='panel filters'><form method='get' action='/glossary'>"
        "<input name='q' placeholder='найти код' value='"
        + html.escape(q)
        + "'/>"
        "<button type='submit'>найти</button></form>"
        + "".join(filters)
        + "</aside><section class='panel'><h2>Словарь кодов</h2>"
        "<table><thead><tr><th>КОД</th><th>НА ЭКРАНЕ</th>"
        "<th>ЧТО ЭТО (факт, не совет)</th></tr></thead><tbody>"
        + ("".join(rows_html) or "<tr><td colspan='3' class='empty'>нет совпадений</td></tr>")
        + "</tbody></table></section><aside class='panel inspect' id='inspect'>"
        + inspect
        + "</aside></div>"
        + _glossary_script(terms, first)
        + chrome_end()
    )
    if contains_advice(page):
        raise ValueError("glossary page must not advise")
    return page


def _glossary_script(terms: list[dict[str, Any]], first: str) -> str:
    payload = {str(t["code"]): {"name": t["name"], "hint": t["hint"]} for t in terms}
    raw = json.dumps(payload, ensure_ascii=False)
    if contains_advice(raw):
        raise ValueError("glossary page must not advise")
    return f"""
<script>
const TERMS = {raw};
function show(code) {{
  const t = TERMS[code];
  if (!t) return;
  document.getElementById('inspect').innerHTML =
    "<p class='mono'>" + code + "</p><h2>" + t.name + "</h2><p>" + t.hint +
    "</p><p class='hint'>коды в журнале английские — сравнимость и хеш-цепь</p>";
  document.querySelectorAll('.term-row').forEach(r =>
    r.classList.toggle('on', r.getAttribute('data-code') === code));
}}
document.querySelectorAll('.term-row').forEach(r => {{
  r.addEventListener('click', () => show(r.getAttribute('data-code')));
}});
if ({json.dumps(first)}) show({json.dumps(first)});
</script>
"""
