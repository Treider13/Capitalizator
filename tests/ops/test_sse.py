"""Э4: SSE /api/stream on a threaded console; chronos listens via EventSource."""

from __future__ import annotations

import json
import socket
import threading
from http.client import HTTPConnection
from pathlib import Path

from capitalizator.ops.console import ConsoleApp, ThreadedHTTPServer, _handler, desk_snapshot
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_chronos_uses_eventsource() -> None:
    html = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "ops" / "chronos.html"
    text = html.read_text(encoding="utf-8")
    assert "EventSource" in text
    assert "/api/stream" in text
    assert "setInterval(refresh, 30000)" in text


def test_snapshot_has_latency_decision_key(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    snap = desk_snapshot(vault)
    assert "latency_decision" in snap
    assert snap["latency_decision"] is None


def _read_until(sock: socket.socket, needle: bytes, *, limit: int = 65_536) -> bytes:
    buf = b""
    while needle not in buf and len(buf) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def test_sse_stream_and_concurrent_get(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = ThreadedHTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.sendall(
            f"GET /api/stream HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Accept: text/event-stream\r\nConnection: keep-alive\r\n\r\n".encode()
        )
        head = _read_until(sock, b"\r\n\r\n")
        assert b"200" in head
        assert b"text/event-stream" in head
        body = head.split(b"\r\n\r\n", 1)[1]
        if b"data:" not in body:
            body += _read_until(sock, b"data:")
        assert b"data:" in body
        line = body.split(b"data:", 1)[1].split(b"\n", 1)[0].strip()
        payload = json.loads(line.decode())
        assert payload.get("refresh") is True

        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"ok"
        conn.close()
    finally:
        sock.close()
        server.shutdown()
        server.server_close()
