"""0.1.3: healthz 200, readyz 503 until recording, no signer import."""

from __future__ import annotations

import threading
from http.client import HTTPConnection
from http.server import HTTPServer

import capitalizator.recorder as recorder_pkg
from capitalizator.recorder.app import RecorderApp, _handler


def test_healthz_readyz() -> None:
    app = RecorderApp()
    assert app.healthz() == 200
    assert app.readyz() == 503
    app.recording = True
    assert app.readyz() == 200


def test_metrics_text() -> None:
    app = RecorderApp()
    app.accepted_count = 3
    text = app.metrics()
    assert "capitalizator_recorder_accepted_total 3" in text


def test_recorder_does_not_import_signer() -> None:
    assert "capitalizator.signer" not in recorder_pkg.__dict__
    assert "signer" not in recorder_pkg.__dict__


def test_live_minutes_refuses_without_a_socket() -> None:
    from capitalizator.recorder.app import main

    try:
        main(["--minutes", "60"])
    except SystemExit as exc:
        assert "live-ws" in str(exc)
        return
    raise AssertionError("minutes must refuse: there is no socket behind it")


def test_http_healthz_readyz_on_real_port() -> None:
    app = RecorderApp()
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/healthz")
        assert conn.getresponse().status == 200
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/readyz")
        assert conn.getresponse().status == 503
        conn.close()
        app.recording = True
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/readyz")
        assert conn.getresponse().status == 200
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
