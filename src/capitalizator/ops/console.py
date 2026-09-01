"""Laptop console. Bind 127.0.0.1. No orders. No keys.

GET is the desk. POST /contour and POST /api/contour may turn the
recording contour on after hours24. POST /order and every other write stay 405.
"""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from capitalizator.ops import chronos_data
from capitalizator.ops.contour import ContourNotReady
from capitalizator.ops.contour import enable as enable_contour
from capitalizator.ops.contour import status as contour_status
from capitalizator.ops.daily_map_report import contains_advice, daily_map_report
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.phase import load_phase, trading_mode
from capitalizator.ops.product import (
    hello_recorded,
    read_user_mode,
    set_user_mode,
)
from capitalizator.ops.vault import (
    Vault,
    init_vault,
    iter_regular_files,
    load_vault,
    open_regular,
)
from capitalizator.risk.session import load_time_config
from capitalizator.screener.universe import load_desk_universe

ADVICE_WORDS = ("лонг", "шорт", "купи", "продай", "завтра")


def _parquet_counts(tape: Path) -> tuple[int, int]:
    if tape.is_symlink():
        raise ValueError(f"symlink: {tape}")
    if not tape.is_dir():
        return 0, 0
    files = [path for path in iter_regular_files(tape) if path.suffix == ".parquet"]
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
    finally:
        knowledge.close()
    files_n, rows_n = _parquet_counts(vault.tape)
    if report_body is None:
        report_body = daily_map_report(day=report_day or "нет даты", rows=[])
        report_day = report_day or "нет даты"
    mode = trading_mode()
    contour = contour_status(vault)
    user = read_user_mode(vault)
    hello_ok = hello_recorded(vault)
    banners: list[str] = []
    if not hello_ok:
        banners.append("Демо: нет hello")
    if n_touches < 20:
        banners.append("мало n")
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
        "last_price": chronos_data.last_prices(vault),
        "session_window": chronos_data.session_window(),
        "last_jury": chronos_data.last_jury(vault),
    }
    text = json.dumps(snap, ensure_ascii=False)
    if contains_advice(text):
        raise ValueError("console snapshot must not advise")
    return snap


def _page(snap: dict[str, Any]) -> str:
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
            f'<button type="submit"{disabled}>Включить контур</button>'
            "</form>"
        )
    else:
        contour_note = "Контур выключен. Суток ленты нет."
        contour_form = (
            '<form method="post" action="/contour">'
            '<input type="hidden" name="action" value="on"/>'
            '<button type="submit" disabled>Включить контур</button>'
            "</form>"
        )
    cav_rows = snap.get("cav_zlg") or []
    if cav_rows:
        cav_html = "".join(
            (
                "<tr>"
                f"<td>{html.escape(str(r['cav']))}</td>"
                f"<td>{html.escape(str(r['zlg']))}</td>"
                f"<td>{html.escape(str(r['outcome']))}</td>"
                f"<td>{int(r['n'])}</td>"
                "</tr>"
            )
            for r in cav_rows
        )
    else:
        cav_html = '<tr><td colspan="4" class="empty">CAV×ZLG×outcome пусто</td></tr>'
    jury_rows = snap.get("jury_today") or []
    if jury_rows:
        jury_html = "".join(
            f"<li>{html.escape(str(r['jury']))}: {int(r['n'])}</li>" for r in jury_rows
        )
    else:
        jury_html = '<li class="empty">жюри дня пусто</li>'
    vs = snap.get("shadow_vs_demo_vs_live") or {}
    learn_n = snap.get("learn_n_days")
    learn_txt = "—" if learn_n is None else str(learn_n)
    service = f"""<div id="service">
      <h2>CAV × ZLG × outcome</h2>
      <table><tbody>{cav_html}</tbody></table>
      <h2>Жюри дня</h2><ul>{jury_html}</ul>
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
        },
        ensure_ascii=False,
    )
    page = template.replace("{{SERVICE}}", service).replace("{{BOOT}}", boot)
    return page


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
        bars = chronos_data.bars_for(vault, symbol=symbol or "", tf=tf, limit=limit)
        return {"symbol": symbol or "", "tf": tf, "bars": bars}
    if path == "/api/zones":
        return {"symbol": symbol or "", "zones": chronos_data.zones_for(vault, symbol=symbol or "")}
    if path == "/api/book":
        return chronos_data.book_for(vault, symbol=symbol or "")
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
            "sources": chronos_data.author_sources(),
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
    return None


def render_html(vault: Vault, *, day: str | None = None) -> str:
    page = _page(desk_snapshot(vault, day=day))
    low = page.lower()
    for word in ADVICE_WORDS:
        if word in low:
            raise ValueError("console page must not advise")
    return page


class ConsoleApp:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault

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
    ) -> dict[str, Any]:
        return set_user_mode(self.vault, mode, ack=ack, learn_n_days=learn_n_days)


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
            raw_ack = payload.get("ack_token", payload.get("ack"))
            ack = raw_ack in {True, "true", "1", 1, "yes"}
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
            try:
                out = app.set_mode(mode, ack=True, learn_n_days=learn_n)
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
                if path == "/order":
                    self._reject_write()
                    return
                if path in {"/api/mode", "/mode"}:
                    if not _is_local(self):
                        self._send(403, b"localhost only", "text/plain; charset=utf-8")
                        return
                    try:
                        payload = _read_body(self)
                    except (ValueError, json.JSONDecodeError):
                        self._send(400, b"bad-mode", "text/plain; charset=utf-8")
                        return
                    self._set_mode(payload, redirect=path == "/mode")
                    return
                if path not in {"/contour", "/api/contour"}:
                    self._reject_write()
                    return
                try:
                    action = _read_action(self)
                except (ValueError, json.JSONDecodeError):
                    self._send(400, b"bad-action", "text/plain; charset=utf-8")
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
                    body = render_html(app.vault).encode()
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

        def do_GET(self) -> None:  # noqa: N802
            started = False
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/healthz":
                    body, code, ctype = b"ok", 200, "text/plain; charset=utf-8"
                elif path == "/api/status":
                    payload = desk_snapshot(app.vault)
                    body = json.dumps(payload, ensure_ascii=False).encode()
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
                    body = render_html(app.vault, day=day).encode()
                    code, ctype = 200, "text/html; charset=utf-8"
                else:
                    body, code, ctype = b"not-found", 404, "text/plain; charset=utf-8"
                self.send_response(code)
                started = True
                self.send_header("Content-Type", ctype)
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
    server = HTTPServer((args.host, args.port), _handler(app))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
