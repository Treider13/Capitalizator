"""P7 — full touch page. B marks + A marks. No advice. No orders."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from capitalizator.card.live import CardLive, card_is_fresh, touch_line
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.desk_chrome import chrome_end, chrome_start
from capitalizator.ops.knowledge import Knowledge

ADVICE = ("лонг", "шорт", "купи", "продай", "завтра")


def _opt_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _idea_side(row: dict[str, Any]) -> str | None:
    raw = row.get("idea_side") or row.get("side")
    if raw in {"buy", "sell"}:
        return str(raw)
    return None


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
    now: datetime | None = None,
    oko_label: str | None = None,
    oko_footprint: str | None = None,
    oko_footprint_side: str | None = None,
    oko_regime: str | None = None,
    oko_n_class: int | None = None,
    oko_set: str | None = None,
    idea_side: str | None = None,
) -> dict[str, Any]:
    """Structured page + text. English tokens only. Footprint is an opinion, not +1."""
    line = touch_line(symbol=symbol, card=card, jury=jury, now=now)
    if card is None:
        verdict = "no card"
        macro = "-"
    elif now is not None and not card_is_fresh(card, symbol=symbol, now=now):
        verdict = "stale"
        macro = str(card.macro_multiplier)
    else:
        verdict = card.bearing_verdict
        macro = str(card.macro_multiplier)
    b = {
        "verdict": verdict,
        "macro": macro,
        "fib": (
            f"{card.fib_level}({card.fib_zone})"
            if card and card.fib_level
            else (card.fib_zone if card else "-")
        ),
        "rsi": card.rsi_htf if card and card.rsi_htf else "-",
        "gex": card.gex_bg if card and card.gex_bg else "-",
        "fvg": card.fvg_status if card else "none",
        "sweep": card.sweep_status if card else "none",
        "sweep_long": card.sweep_long if card else "none",
        "sweep_short": card.sweep_short if card else "none",
        "sweep_for": (
            card.sweep_for("sell" if idea_side == "sell" else "buy") if card else "none"
        ),
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
        "oko_label": oko_label or "-",
        "oko_footprint": oko_footprint or "-",
        "oko_footprint_side": oko_footprint_side or "-",
        "oko_regime": oko_regime or "-",
        "oko_n_class": "-" if oko_n_class is None else str(oko_n_class),
        "oko_set": oko_set or "-",
        "idea_side": idea_side or "-",
    }
    plus = ",".join(b["pluses"]) if b["pluses"] else "-"
    minus = ",".join(b["minuses"]) if b["minuses"] else "-"
    text = (
        f"{line}\n"
        f"--- B ---\n"
        f"verdict:{b['verdict']} macro:{b['macro']} venue:{b['venue']}\n"
        f"fib:{b['fib']} rsi:{b['rsi']} gex:{b['gex']}\n"
        f"fvg:{b['fvg']} sweep_for:{b['sweep_for']} "
        f"sweep_long:{b['sweep_long']} sweep_short:{b['sweep_short']} "
        f"ob:{b['ob']} bos:{b['bos']} regime:{b['regime']}\n"
        f"poc:{b['poc']} vah:{b['vah']} val:{b['val']} rvol:{b['rvol']}\n"
        f"plus:{plus}\n"
        f"minus:{minus}\n"
        f"--- A ---\n"
        f"jury:{a['jury']} skip:{a['skip']}\n"
        f"cav:{a['cav']} n={a['n_cav']} zlg:{a['zlg']} n={a['n_zlg']}\n"
        f"tape_eaten:{a['tape_eaten']} btc:{a['btc']}\n"
        f"oko_label:{a['oko_label']} oko_footprint:{a['oko_footprint']} "
        f"oko_side:{a['oko_footprint_side']} oko_regime:{a['oko_regime']}\n"
        f"oko_n_class:{a['oko_n_class']} oko_set:{a['oko_set']}\n"
    )
    if contains_advice(text):
        raise ValueError("touch screen must not advise")
    return {"symbol": symbol, "line": line, "b": b, "a": a, "text": text}


def from_journal(
    row: dict[str, Any],
    card: CardLive | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
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
        oko_label=None if row.get("oko_label") is None else str(row.get("oko_label")),
        oko_footprint=None if row.get("oko_footprint") is None else str(row.get("oko_footprint")),
        oko_footprint_side=(
            None if row.get("oko_footprint_side") is None else str(row.get("oko_footprint_side"))
        ),
        oko_regime=None if row.get("oko_regime") is None else str(row.get("oko_regime")),
        oko_n_class=_opt_int(row.get("oko_n_class")),
        oko_set=None if row.get("oko_set") is None else str(row.get("oko_set")),
        idea_side=_idea_side(row),
        now=now,
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
    return from_journal(row, card, now=datetime.now(tz=UTC))


def render_html(screen: dict[str, Any] | None) -> str:
    if screen is None:
        body = '<p class="empty">касаний нет</p>'
        title = "Касание"
        extra = ""
    else:
        b = screen["b"]
        a = screen["a"]
        plus = html.escape(",".join(b["pluses"]) if b["pluses"] else "-")
        minus = html.escape(",".join(b["minuses"]) if b["minuses"] else "-")
        extra = (
            "<div class='touch-grid'>"
            "<section class='panel'><h2>кадр</h2>"
            f"<pre class='flight'>{html.escape(screen['line'])}</pre>"
            f"<p class='hint'>символ {html.escape(str(screen['symbol']))}</p></section>"
            "<section class='panel'><h3>B</h3>"
            "<p class='hint'>метки карточки, не совет</p>"
            "<table>"
            f"<tr><th>verdict</th><td>{html.escape(str(b['verdict']))}</td><th>macro</th><td>{html.escape(str(b['macro']))}</td></tr>"
            f"<tr><th>fib</th><td>{html.escape(str(b['fib']))}</td><th>rsi</th><td>{html.escape(str(b['rsi']))}</td></tr>"
            f"<tr><th>gex</th><td>{html.escape(str(b['gex']))}</td><th>fvg</th><td>{html.escape(str(b['fvg']))}</td></tr>"
            f"<tr><th>sweep_for</th><td>{html.escape(str(b['sweep_for']))}</td>"
            f"<th>idea_side</th><td>{html.escape(str(a['idea_side']))}</td></tr>"
            f"<tr><th>sweep_long</th><td>{html.escape(str(b['sweep_long']))}</td>"
            f"<th>sweep_short</th><td>{html.escape(str(b['sweep_short']))}</td></tr>"
            f"<tr><th>ob/bos</th><td>{html.escape(str(b['ob']))}/{html.escape(str(b['bos']))}</td>"
            f"<th>regime</th><td>{html.escape(str(b['regime']))}</td></tr>"
            f"<tr><th>poc</th><td>{html.escape(str(b['poc']))}</td><th>vah/val</th><td>{html.escape(str(b['vah']))}/{html.escape(str(b['val']))}</td></tr>"
            f"<tr><th>rvol</th><td>{html.escape(str(b['rvol']))}</td><th>venue</th><td>{html.escape(str(b['venue']))}</td></tr>"
            "</table>"
            f"<p class='plus'>plus: {plus}</p>"
            f"<p class='minus'>minus: {minus}</p>"
            "<h3>A</h3>"
            "<p class='hint'>голоса книги и ленты</p>"
            "<table>"
            f"<tr><th>jury</th><td>{html.escape(str(a['jury']))}</td><th>skip</th><td>{html.escape(str(a['skip']))}</td></tr>"
            f"<tr><th>cav</th><td>{html.escape(str(a['cav']))} n={int(a['n_cav'])}</td>"
            f"<th>zlg</th><td>{html.escape(str(a['zlg']))} n={int(a['n_zlg'])}</td></tr>"
            f"<tr><th>tape_eaten</th><td>{html.escape(str(a['tape_eaten']))}</td><th>btc</th><td>{html.escape(str(a['btc']))}</td></tr>"
            f"<tr><th>oko_label</th><td>{html.escape(str(a['oko_label']))}</td>"
            f"<th>oko_regime</th><td>{html.escape(str(a['oko_regime']))}</td></tr>"
            f"<tr><th>oko_footprint</th>"
            f"<td>{html.escape(str(a['oko_footprint']))} {html.escape(str(a['oko_footprint_side']))}</td>"
            f"<th>oko_n_class / set</th>"
            f"<td>{html.escape(str(a['oko_n_class']))} / {html.escape(str(a['oko_set']))}</td></tr>"
            "</table></section>"
            "<section class='panel'><h2>Почему не зашли</h2>"
            f"<p>{html.escape(str(a['skip']))}</p>"
            "<h2>Почему зашли бы</h2>"
            f"<p>{html.escape(str(a.get('shadow') or '—'))}</p>"
            "<p class='empty'>страница не советует и ордер не шлёт</p></section></div>"
        )
        title = f"Касание {html.escape(str(screen['symbol']))}"
        body = extra
    page = (
        chrome_start(title=title, active="touch")
        + "<div class='page-body'><h1>"
        + title
        + '</h1><p class="empty">только метки. ордеров нет.</p>'
        + body
        + "</div>"
        + chrome_end()
    )
    low = page.lower()
    for word in ADVICE:
        if word in low:
            raise ValueError("touch page must not advise")
    return page
