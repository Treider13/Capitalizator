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

from capitalizator.ops.contour import ContourNotReady
from capitalizator.ops.contour import enable as enable_contour
from capitalizator.ops.contour import status as contour_status
from capitalizator.ops.daily_map_report import contains_advice, daily_map_report
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.phase import trading_mode
from capitalizator.ops.product import (
    hello_recorded,
    read_user_mode,
    set_user_mode,
)
from capitalizator.screener.universe import load_desk_universe
from capitalizator.ops.vault import (
    Vault,
    init_vault,
    iter_regular_files,
    load_vault,
    open_regular,
)

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


def desk_snapshot(vault: Vault, *, day: str | None = None) -> dict[str, Any]:
    n_days = None
    n_touches = 0
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
        if knowledge.available() and knowledge._cx is not None:
            try:
                row = knowledge._cx.execute(
                    "SELECT COUNT(*) AS n FROM journal_touches"
                ).fetchone()
                n_touches = int(row["n"]) if row is not None else 0
            except Exception:
                n_touches = 0
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
    banner = "" if hello_ok else "нет testnet hello — send закрыт"
    symbols = list(load_desk_universe().symbols)
    snap = {
        "trading_mode": mode,
        "user_mode": user,
        "hello_ok": hello_ok,
        "hello_banner": banner,
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
    }
    text = json.dumps(snap, ensure_ascii=False)
    if contains_advice(text):
        raise ValueError("console snapshot must not advise")
    return snap


def _page(snap: dict[str, Any]) -> str:
    episodes = snap["episodes"]
    if episodes:
        rows_html = "".join(
            (
                "<tr>"
                f"<td>{html.escape(e['trade_id'])}</td>"
                f"<td>{html.escape(e['mode'])}</td>"
                f"<td>{html.escape(e['zone_id'][:12])}</td>"
                f"<td>{html.escape(e['gesture'])}</td>"
                f"<td>{html.escape(e['r'])}</td>"
                "</tr>"
            )
            for e in episodes
        )
    else:
        rows_html = (
            '<tr><td colspan="5" class="empty">Сделок нет. Журнал пустой — так и должно быть '
            "пока нет демо.</td></tr>"
        )
    chain = "целая" if snap["hash_chain_ok"] else "сломана"
    mode = html.escape(str(snap["trading_mode"]))
    user_mode = html.escape(str(snap.get("user_mode") or "off"))
    hello_banner = html.escape(str(snap.get("hello_banner") or ""))
    hello_ok = bool(snap.get("hello_ok"))
    report = html.escape(str(snap["report"]))
    contour = html.escape(str(snap["contour"]))
    hours24 = bool(snap["hours24"])
    can_enable = bool(snap["can_enable"])
    if snap["contour"] == "on":
        contour_note = "Контур включён. Метки пишутся. Ордеров нет."
        contour_form = ""
        contour_pill = "ok"
    elif hours24:
        contour_note = "Сутки ленты есть. Кнопка включает запись меток, не торги."
        disabled = "" if can_enable else " disabled"
        contour_form = (
            '<form method="post" action="/contour">'
            '<input type="hidden" name="action" value="on"/>'
            f'<button type="submit"{disabled}>Включить контур</button>'
            "</form>"
        )
        contour_pill = "ok"
    else:
        contour_note = "Контур выключен. Суток ленты нет."
        contour_form = (
            '<form method="post" action="/contour">'
            '<input type="hidden" name="action" value="on"/>'
            '<button type="submit" disabled>Включить контур</button>'
            "</form>"
        )
        contour_pill = ""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Стол — отчёты</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a222c;
      --line: #2a3542;
      --text: #e8eef4;
      --muted: #8b9aab;
      --ok: #3dba7a;
      --warn: #e0b44d;
      --bad: #d45b5b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.45;
    }}
    header {{
      padding: 28px 32px 12px; border-bottom: 1px solid var(--line);
    }}
    header h1 {{ margin: 0; font-size: 22px; font-weight: 600; }}
    header p {{ margin: 8px 0 0; color: var(--muted); font-size: 14px; }}
    main {{
      display: grid; gap: 16px; padding: 24px 32px 48px;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }}
    .wide {{ grid-column: 1 / -1; }}
    .card {{
      background: var(--card); border: 1px solid var(--line);
      border-radius: 12px; padding: 18px 20px;
    }}
    .card h2 {{ margin: 0 0 12px; font-size: 15px; color: var(--muted); font-weight: 500; }}
    .num {{ font-size: 28px; font-weight: 650; letter-spacing: -0.03em; }}
    .pill {{
      display: inline-block; padding: 2px 8px; border-radius: 999px;
      font-size: 12px; background: #243041; color: var(--warn);
    }}
    .pill.ok {{ color: var(--ok); }}
    .pill.bad {{ color: var(--bad); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 500; }}
    pre {{
      white-space: pre-wrap; margin: 0; font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 13px; color: var(--text);
    }}
    .empty {{ color: var(--muted); }}
    button {{
      margin-top: 10px; padding: 8px 14px; border-radius: 8px; border: 1px solid var(--line);
      background: #2a3d52; color: var(--text); font-size: 14px; cursor: pointer;
    }}
    button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    footer {{ padding: 0 32px 32px; color: var(--muted); font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <h1>Стол</h1>
    <p>Только просмотр. Ордеров отсюда нет. Пустой журнал — честно, не ошибка.</p>
  </header>
  <main>
    <section class="card">
      <h2>Режим yaml</h2>
      <div class="num">{mode}</div>
      <p><span class="pill">торги с консоли нельзя</span></p>
    </section>
    <section class="card">
      <h2>Режим человека</h2>
      <div class="num">{user_mode}</div>
      <p><span class="pill {"ok" if hello_ok else "bad"}">{hello_banner or "testnet hello есть"}</span></p>
      <form method="post" action="/api/mode">
        <input type="hidden" name="ack" value="1"/>
        <button type="submit" name="mode" value="off">off</button>
        <button type="submit" name="mode" value="learn">learn</button>
        <button type="submit" name="mode" value="demo">demo</button>
        <button type="submit" name="mode" value="live">live</button>
      </form>
    </section>
    <section class="card">
      <h2>Контур</h2>
      <div class="num">{contour}</div>
      <p><span class="pill {contour_pill}">{html.escape(contour_note)}</span></p>
      {contour_form}
    </section>
    <section class="card">
      <h2>Сделки в журнале</h2>
      <div class="num">{snap["n_episode"]}</div>
      <p class="empty">{html.escape(str(snap["honest"]))}</p>
    </section>
    <section class="card">
      <h2>Цепочка знаний</h2>
      <div class="num">{snap["n_hash"]}</div>
      <p><span class="pill {"ok" if snap["hash_chain_ok"] else "bad"}">{chain}</span></p>
    </section>
    <section class="card">
      <h2>Лента parquet</h2>
      <div class="num">{snap["parquet_files"]}</div>
      <p class="empty">{snap["parquet_rows"]} строк. Нет файла — нет суток VPS.</p>
    </section>
    <section class="card wide">
      <h2>Отчёт · {html.escape(str(snap["report_day"]))}</h2>
      <pre>{report}</pre>
    </section>
    <section class="card wide">
      <h2>Журнал сделок</h2>
      <table>
        <thead><tr><th>id</th><th>режим</th><th>зона</th><th>жест</th><th>R</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
  </main>
  <footer>
    С ноута: ssh -L 8082:127.0.0.1:8082 user@vps затем открыть эту страницу.
    Ключи и секреты сюда не попадают.
  </footer>
</body>
</html>
"""


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
