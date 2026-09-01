"""P7 — full touch page. B marks + A marks. No advice. No orders."""

from __future__ import annotations

import html
from typing import Any

from capitalizator.card.live import CardLive, touch_line
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.knowledge import Knowledge

ADVICE = ("лонг", "шорт", "купи", "продай", "завтра")


def _yn(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def touch_screen(
    *,
    symbol: str,
    card: CardLive | None,
    jury: str | None = None,
    cav: str | None = None,
    zlg: str | None = None,
    tape_eaten: bool | None = None,
    btc: str | None = None,
    n_cav: int = 0,
    n_zlg: int = 0,
    skip: str | None = None,
) -> dict[str, Any]:
    """Structured page + text. English tokens only."""
    line = touch_line(symbol=symbol, card=card, jury=jury)
    b = {
        "verdict": card.bearing_verdict if card else "hold",
        "macro": str(card.macro_multiplier) if card else "1",
        "fib": (
            f"{card.fib_level}({card.fib_zone})"
            if card and card.fib_level
            else (card.fib_zone if card else "-")
        ),
        "rsi": card.rsi_htf if card and card.rsi_htf else "-",
        "gex": card.gex_bg if card and card.gex_bg else "-",
        "fvg": card.fvg_status if card else "none",
        "sweep": card.sweep_status if card else "none",
        "ob": card.ob_status if card and card.ob_status else "-",
        "bos": card.bos_status if card and card.bos_status else "-",
        "regime": card.market_regime if card else "none",
        "rvol": card.volume.rvol if card and card.volume.rvol else "-",
        "poc": card.volume.poc if card and card.volume.poc else "-",
        "vah": card.volume.vah if card and card.volume.vah else "-",
        "val": card.volume.val if card and card.volume.val else "-",
        "pluses": list(card.pluses) if card else [],
        "minuses": list(card.minuses) if card else [],
        "venue": card.venue if card else "perp",
    }
    a = {
        "jury": jury or "none",
        "cav": cav or "-",
        "zlg": zlg or "-",
        "n_cav": n_cav,
        "n_zlg": n_zlg,
        "tape_eaten": _yn(tape_eaten),
        "btc": btc or "-",
        "skip": skip or "-",
    }
    plus = ",".join(b["pluses"]) if b["pluses"] else "-"
    minus = ",".join(b["minuses"]) if b["minuses"] else "-"
    text = (
        f"{line}\n"
        f"--- B ---\n"
        f"verdict:{b['verdict']} macro:{b['macro']} venue:{b['venue']}\n"
        f"fib:{b['fib']} rsi:{b['rsi']} gex:{b['gex']}\n"
        f"fvg:{b['fvg']} sweep:{b['sweep']} ob:{b['ob']} bos:{b['bos']} regime:{b['regime']}\n"
        f"poc:{b['poc']} vah:{b['vah']} val:{b['val']} rvol:{b['rvol']}\n"
        f"plus:{plus}\n"
        f"minus:{minus}\n"
        f"--- A ---\n"
        f"jury:{a['jury']} skip:{a['skip']}\n"
        f"cav:{a['cav']} n={a['n_cav']} zlg:{a['zlg']} n={a['n_zlg']}\n"
        f"tape_eaten:{a['tape_eaten']} btc:{a['btc']}\n"
    )
    if contains_advice(text):
        raise ValueError("touch screen must not advise")
    return {"symbol": symbol, "line": line, "b": b, "a": a, "text": text}


def from_journal(row: dict[str, Any], card: CardLive | None) -> dict[str, Any]:
    symbol = str(row.get("symbol") or (card.symbol if card else "BTCUSDT"))
    return touch_screen(
        symbol=symbol,
        card=card,
        jury=None if row.get("jury") is None else str(row.get("jury")),
        cav=None if row.get("cav_label") is None else str(row.get("cav_label")),
        zlg=None if row.get("zlg_label") is None else str(row.get("zlg_label")),
        tape_eaten=row.get("tape_eaten") if isinstance(row.get("tape_eaten"), bool) else None,
        btc=None if row.get("btc_state") is None else str(row.get("btc_state")),
        n_cav=int(row.get("n_cav") or 0),
        n_zlg=int(row.get("n_zlg") or 0),
        skip=None if row.get("skip_reason") is None else str(row.get("skip_reason")),
    )


def latest(knowledge: Knowledge) -> dict[str, Any] | None:
    rows = knowledge.journal_rows()
    if not rows:
        return None
    row = rows[-1]
    symbol = str(row.get("symbol") or "")
    card = None
    if symbol:
        raw = knowledge.get_card_live(symbol)
        if raw is not None:
            card = CardLive.from_payload(raw)
    return from_journal(row, card)


def render_html(screen: dict[str, Any] | None) -> str:
    if screen is None:
        body = '<p class="empty">касаний нет</p>'
        title = "Касание"
    else:
        b = screen["b"]
        a = screen["a"]
        plus = html.escape(",".join(b["pluses"]) if b["pluses"] else "-")
        minus = html.escape(",".join(b["minuses"]) if b["minuses"] else "-")
        body = f"""
<pre>{html.escape(screen["line"])}</pre>
<h3>B</h3>
<table>
<tr><th>verdict</th><td>{html.escape(str(b["verdict"]))}</td><th>macro</th><td>{html.escape(str(b["macro"]))}</td></tr>
<tr><th>fib</th><td>{html.escape(str(b["fib"]))}</td><th>rsi</th><td>{html.escape(str(b["rsi"]))}</td></tr>
<tr><th>gex</th><td>{html.escape(str(b["gex"]))}</td><th>fvg</th><td>{html.escape(str(b["fvg"]))}</td></tr>
<tr><th>sweep</th><td>{html.escape(str(b["sweep"]))}</td><th>ob/bos</th><td>{html.escape(str(b["ob"]))}/{html.escape(str(b["bos"]))}</td></tr>
<tr><th>regime</th><td>{html.escape(str(b["regime"]))}</td></tr>
<tr><th>poc</th><td>{html.escape(str(b["poc"]))}</td><th>vah/val</th><td>{html.escape(str(b["vah"]))}/{html.escape(str(b["val"]))}</td></tr>
<tr><th>rvol</th><td>{html.escape(str(b["rvol"]))}</td><th>venue</th><td>{html.escape(str(b["venue"]))}</td></tr>
</table>
<p>plus: {plus}</p>
<p>minus: {minus}</p>
<h3>A</h3>
<table>
<tr><th>jury</th><td>{html.escape(str(a["jury"]))}</td><th>skip</th><td>{html.escape(str(a["skip"]))}</td></tr>
<tr><th>cav</th><td>{html.escape(str(a["cav"]))} n={int(a["n_cav"])}</td>
<th>zlg</th><td>{html.escape(str(a["zlg"]))} n={int(a["n_zlg"])}</td></tr>
<tr><th>tape</th><td>{html.escape(str(a["tape_eaten"]))}</td><th>btc</th><td>{html.escape(str(a["btc"]))}</td></tr>
</table>
"""
        title = f"Касание {html.escape(str(screen['symbol']))}"
    page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/><title>{title}</title>
<style>
body {{ background:#0f1419; color:#e8eef4; font-family:sans-serif; margin:24px; }}
th {{ color:#8b9aab; text-align:left; padding:6px; }}
td {{ padding:6px; }}
.empty {{ color:#8b9aab; }}
pre {{ font-family:ui-monospace,monospace; }}
</style></head><body>
<h1>{title}</h1>
<p class="empty">только метки. ордеров нет.</p>
{body}
</body></html>
"""
    low = page.lower()
    for word in ADVICE:
        if word in low:
            raise ValueError("touch page must not advise")
    return page
