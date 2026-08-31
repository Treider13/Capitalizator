"""Recorder process: health only. No signer import. No keys."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class RecorderApp:
    """In-process status. Recording flag is explicit; default is not ready."""

    def __init__(self) -> None:
        self.recording = False
        self.accepted_count = 0

    def healthz(self) -> int:
        return 200

    def readyz(self) -> int:
        return 200 if self.recording else 503

    def metrics(self) -> str:
        return (
            "# HELP capitalizator_recorder_accepted_total Events written\n"
            "# TYPE capitalizator_recorder_accepted_total counter\n"
            f"capitalizator_recorder_accepted_total {self.accepted_count}\n"
        )


def _handler(app: RecorderApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                body, code = b"ok", app.healthz()
            elif self.path == "/readyz":
                body, code = (b"ready" if app.recording else b"not-recording"), app.readyz()
            elif self.path == "/metrics":
                body, code = app.metrics().encode(), 200
            else:
                body, code = b"not-found", 404
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capitalizator recorder (no keys)")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--stream", default="trades")
    parser.add_argument("--minutes", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    app = RecorderApp()
    if args.minutes and args.minutes > 0:
        # Live hour is step 0.1.4 green on a VPS. This process does not open WS here.
        raise SystemExit(
            "live WS hour is not enabled in this binary; use tests/fixtures and a VPS later"
        )
    if args.serve:
        server = HTTPServer((args.host, args.port), _handler(app))
        server.serve_forever()
        return 0
    print(json.dumps({"healthz": app.healthz(), "readyz": app.readyz(), "symbol": args.symbol}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
