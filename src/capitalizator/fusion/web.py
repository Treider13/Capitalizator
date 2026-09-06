"""Loopback console. Two venue modes, separate pause/close controls, CSRF token."""

from __future__ import annotations

import hmac
import json
import secrets
import socket
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from capitalizator.fusion.console_records import records

PAGE = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
ASSETS = {
    "/assets/" + name: (Path(__file__).with_name(name).read_bytes(), mime)
    for name, mime in (
        ("dashboard.css", "text/css; charset=utf-8"),
        ("dashboard.js", "text/javascript; charset=utf-8"),
        ("chart.js", "text/javascript; charset=utf-8"),
        ("depth.js", "text/javascript; charset=utf-8"),
    )
}


class ConsoleServer(ThreadingHTTPServer):
    """Join handlers after waking clients blocked in request/header reads."""

    daemon_threads = False
    block_on_close = True

    def __init__(self, address: Any, handler: Any) -> None:
        self.clients: set[socket.socket] = set()
        self.clients_lock = threading.Lock()
        self.closing = False
        super().__init__(address, handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        with self.clients_lock:
            if self.closing:
                self.shutdown_request(request)
                return
            self.clients.add(request)
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.clients.discard(request)
                raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.clients_lock:
                self.clients.discard(request)

    def server_close(self) -> None:
        with self.clients_lock:
            self.closing = True
            for client in self.clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # Handler may already have completed the socket close.
        super().server_close()


def server(runtime: Any, port: int) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)
    instance = secrets.token_hex(16)
    streams = threading.BoundedSemaphore(8)

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
            assert isinstance(self.server, ThreadingHTTPServer)
            bound_port = self.server.server_port
            return self.headers.get("Host", "") in {
                f"127.0.0.1:{bound_port}",
                f"localhost:{bound_port}",
            }

        def do_GET(self) -> None:
            if not self.trusted_host():
                self.send(403, b'{"error":"host"}')
                return
            if self.path == "/":
                self.send(
                    200,
                    PAGE.replace("__TOKEN__", token).replace("__INSTANCE__", instance).encode(),
                    "text/html; charset=utf-8",
                )
            elif self.path in ASSETS:
                content, mime = ASSETS[self.path]
                self.send(200, content, mime)
            elif urlparse(self.path).path == "/api/records":
                query = parse_qs(urlparse(self.path).query)
                try:
                    limit = int(query.get("limit", ["20"])[0])
                    before = int(query["before"][0]) if "before" in query else None
                    with runtime.shared.lock:
                        mode = runtime.shared.mode
                    body = records(runtime.store, mode, query.get("kind", [""])[0], limit, before)
                    self.send(200, json.dumps(body, allow_nan=False).encode())
                except ValueError as exc:
                    self.send(400, json.dumps({"error": str(exc)}).encode())
                except sqlite3.OperationalError:
                    self.send(503, b'{"error":"journal read unavailable or time budget exceeded"}')
            elif urlparse(self.path).path == "/api/stream":
                query = parse_qs(urlparse(self.path).query)
                symbol = query.get("symbol", [runtime.config.symbols[0]])[0]
                tf = query.get("tf", ["1m"])[0]
                try:
                    first = runtime.chart(symbol, tf)
                except ValueError:
                    self.send(400, b'{"error":"chart parameters"}')
                    return
                if not streams.acquire(blocking=False):
                    self.send(429, b'{"error":"stream limit"}')
                    return
                try:
                    self.connection.settimeout(5)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    body = {**first, "console_instance": instance}
                    while not runtime.supervisor.stop.is_set():
                        self.wfile.write(
                            b"data: " + json.dumps(body, allow_nan=False).encode() + b"\n\n"
                        )
                        self.wfile.flush()
                        if runtime.supervisor.stop.wait(runtime.config.chart_refresh_s):
                            break
                        body = {
                            **runtime.chart(symbol, tf, body["revision"]),
                            "console_instance": instance,
                        }
                except (OSError, ConnectionError):
                    pass
                finally:
                    streams.release()
            elif self.path == "/api/status":
                body = {**runtime.status(), "console_instance": instance}
                self.send(200, json.dumps(body, allow_nan=False).encode())
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

    http = ConsoleServer(("127.0.0.1", port), Handler)
    return http
