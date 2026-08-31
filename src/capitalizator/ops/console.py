"""Read-only laptop console. Bind 127.0.0.1. No orders. No keys.

FreqUI idea: look at the desk from the notebook via SSH tunnel.
Unlike freqUI we have no force-entry — GET only.
"""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from capitalizator.ops.daily_map_report import contains_advice, daily_map_report
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.phase import trading_mode
from capitalizator.ops.vault import Vault, init_vault, iter_regular_files, load_vault

ADVICE_WORDS = ("лонг", "шорт", "купи", "продай", "завтра")


def _parquet_counts(tape: Path) -> tuple[int, int]:
    if tape.is_symlink():
        raise ValueError(f"symlink: {tape}")
    if not tape.is_dir():
        return 0, 0
    files = [path for path in iter_regular_files(tape) if path.suffix == ".parquet"]
    rows = 0
    if files:
        import pyarrow.parquet as pq

        for path in files:
            meta = pq.ParquetFile(path).metadata
            if meta is None:
                raise ValueError(f"parquet metadata missing: {path}")
            rows += int(meta.num_rows)
    return len(files), rows


def desk_snapshot(vault: Vault, *, day: str | None = None) -> dict[str, Any]:
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
    finally:
        knowledge.close()
    files_n, rows_n = _parquet_counts(vault.tape)
    if report_body is None:
        report_body = daily_map_report(day=report_day or "нет даты", rows=[])
        report_day = report_day or "нет даты"
    mode = trading_mode()
    snap = {
        "trading_mode": mode,
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
    report = html.escape(str(snap["report"]))
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
      <h2>Режим</h2>
      <div class="num">{mode}</div>
      <p><span class="pill">торги с консоли нельзя</span></p>
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


def _handler(app: ConsoleApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _reject_write(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"read-only")

        def do_POST(self) -> None:  # noqa: N802
            self._reject_write()

        def do_PUT(self) -> None:  # noqa: N802
            self._reject_write()

        def do_DELETE(self) -> None:  # noqa: N802
            self._reject_write()

        def do_PATCH(self) -> None:  # noqa: N802
            self._reject_write()

        def do_GET(self) -> None:  # noqa: N802
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
                self.send_header("Content-Type", ctype)
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"error")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only desk console")
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
