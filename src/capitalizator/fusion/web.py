"""Loopback console. Two venue modes, separate pause/close controls, CSRF token."""

from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PAGE = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")


def server(runtime: Any, port: int) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return  # Requests may carry control data; decisions are logged structurally.

        def send(self, code: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self) -> bool:
            return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self) -> None:
            if not self.trusted_host():
                self.send(403, b'{"error":"host"}')
                return
            if self.path == "/":
                self.send(
                    200, PAGE.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8"
                )
            elif self.path == "/api/status":
                self.send(200, json.dumps(runtime.status(), allow_nan=False).encode())
            else:
                self.send(404, b"{}")

        def do_POST(self) -> None:
            origin = self.headers.get("Origin")
            if (
                not self.trusted_host()
                or not hmac.compare_digest(self.headers.get("X-Control-Token", ""), token)
                or (origin and urlparse(origin).netloc != self.headers.get("Host"))
            ):
                self.send(403, b'{"error":"control authorization"}')
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("invalid request size")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("object required")
                action = self.path.removeprefix("/api/")
                result = runtime.control(action, body)
                self.send(200, json.dumps(result).encode())
            except (ValueError, KeyError) as exc:
                self.send(400, json.dumps({"error": str(exc)}).encode())

    http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    http.daemon_threads = True
    return http
