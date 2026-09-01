"""Laptop console: GET plus contour POST. No orders. No signer."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path

import pytest

import capitalizator.ops.console as console_pkg
from capitalizator.ops.console import ConsoleApp, _handler, desk_snapshot, render_html
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.phase import trading_mode
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent


def test_empty_snapshot_is_honest(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    snap = desk_snapshot(vault)
    assert snap["trading_mode"] == "off"
    assert snap["contour"] == "off"
    assert snap["hours24"] is False
    assert snap["hours24_span_s"] is None
    assert snap["can_enable"] is False
    assert snap["n_episode"] == 0
    assert snap["n_hash"] == 0
    assert snap["parquet_files"] == 0
    assert snap["hash_chain_ok"] is True
    assert snap["episodes"] == []
    assert "vps" not in snap
    assert "Касаний нет" in snap["report"]
    assert "пусто" in snap["honest"]
    for word in ("лонг", "шорт", "купи", "продай", "завтра"):
        blob = json.dumps(snap, ensure_ascii=False).lower()
        assert word not in blob


def test_html_has_no_advice(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    page = render_html(vault)
    low = page.lower()
    assert "сделок нет" in low
    assert "торги с консоли нельзя" in low
    assert '<button type="submit" disabled>Включить контур</button>' in page
    assert "суток ленты нет" in low
    for word in ("лонг", "шорт", "купи", "продай", "завтра"):
        assert word not in low


def test_console_does_not_import_signer() -> None:
    assert "capitalizator.signer" not in console_pkg.__dict__
    assert "signer" not in console_pkg.__dict__


def test_http_get_and_post_readonly(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
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
        conn.request("GET", "/api/status")
        resp = conn.getresponse()
        assert resp.status == 200
        payload = json.loads(resp.read().decode())
        assert payload["n_episode"] == 0
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode()
        assert "Стол" in body
        assert "Касаний нет" in body
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("POST", "/order", body="{}", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 405
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/contour",
            body='{"action":"on"}',
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 409
        denied = json.loads(resp.read().decode())
        assert denied["ok"] is False
        assert denied["contour"] == "off"
        assert denied["hours24"] is False
        assert denied["trading_mode"] == "off"
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("PUT", "/api/status", body="{}", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 405
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_http_error_is_plain_500(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    target = tmp_path / "outside.txt"
    target.write_text("secret-target\n", encoding="utf-8")
    (vault.tape / "leak.parquet").symlink_to(target)
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/api/status")
        resp = conn.getresponse()
        assert resp.status == 500
        assert resp.read() == b"error"
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_cli_refuses_public_bind(tmp_path: Path) -> None:
    from capitalizator.ops.console import main

    try:
        main(["--userdir", str(tmp_path / "desk"), "--host", "0.0.0.0", "--init"])
    except SystemExit as exc:
        assert "localhost" in str(exc)
        return
    raise AssertionError("public bind must refuse")


def test_serve_without_layout_does_not_invent_vault(tmp_path: Path) -> None:
    from capitalizator.ops.console import main

    with pytest.raises(FileNotFoundError, match="not a vault"):
        main(["--userdir", str(tmp_path / "missing"), "--serve"])


def test_snapshot_does_not_init_empty_sqlite(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    vault.db_path.write_bytes(b"")
    with pytest.raises(ValueError, match="empty knowledge db"):
        desk_snapshot(vault)
    assert vault.db_path.read_bytes() == b""


def test_snapshot_refuses_symlink_db(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    real = vault.db_path
    other = tmp_path / "other.sqlite"
    real.rename(other)
    real.symlink_to(other)
    with pytest.raises(ValueError, match="symlink"):
        desk_snapshot(vault)


def test_snapshot_refuses_tape_symlink(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    target = tmp_path / "outside.txt"
    target.write_text("secret-target\n", encoding="utf-8")
    (vault.tape / "leak.parquet").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        desk_snapshot(vault)


def _hours24_tape(tape: Path) -> None:
    start = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    end = start + timedelta(hours=24)

    def ev(stream: str, ts: datetime, payload: dict) -> MarketEvent:
        return MarketEvent(
            stream=stream,
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=ts,
            recv_ts=ts,
            seq=None,
            payload=payload,
        )

    sink = ParquetSink(tape)
    sink.write(ev("trades", start, {"px": "1", "qty": "0.001", "side": "buy"}))
    sink.write(ev("trades", end, {"px": "1", "qty": "0.001", "side": "buy"}))
    sink.write(
        ev(
            "gap",
            start,
            {"ts_from": start.isoformat(), "ts_to": end.isoformat()},
        )
    )


def test_desk_snapshot_skips_corrupt_parquet(tmp_path: Path) -> None:
    """A half-written .parquet must not 500 the desk or hide a green day."""
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    _hours24_tape(vault.tape)
    broken = vault.tape / "BTCUSDT" / "broken.parquet"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"not parquet")
    snap = desk_snapshot(vault)
    assert snap["hours24"] is True
    assert snap["can_enable"] is True
    assert snap["parquet_files"] == 3
    assert snap["parquet_rows"] == 3
    page = render_html(vault)
    assert '<button type="submit">Включить контур</button>' in page


def test_http_enable_after_hours24(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    _hours24_tape(vault.tape)
    page = render_html(vault)
    assert '<button type="submit">Включить контур</button>' in page
    assert '<button type="submit" disabled>' not in page
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/contour",
            body='{"action":"on"}',
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 200
        payload = json.loads(resp.read().decode())
        assert payload["ok"] is True
        assert payload["contour"] == "on"
        assert payload["trading_mode"] == "off"
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/api/status")
        status = json.loads(conn.getresponse().read().decode())
        assert status["contour"] == "on"
        assert status["trading_mode"] == "off"
        assert "vps" not in status
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("POST", "/order", body="{}", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 405
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    assert trading_mode() == "off"


def test_http_form_enable_redirects(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    _hours24_tape(vault.tape)
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/contour",
            body="action=on",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        assert resp.status == 303
        assert resp.getheader("Location") == "/"
        resp.read()
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/")
        page = conn.getresponse().read().decode()
        assert "Контур включён" in page
        assert "Включить контур" not in page
        conn.close()
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/contour",
            body="action=off",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        bad = conn.getresponse()
        assert bad.status == 400
        assert bad.read() == b"bad-action"
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    assert trading_mode() == "off"


def test_http_form_without_hours24_is_409_html(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/contour",
            body="action=on",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        assert resp.status == 409
        page = resp.read().decode()
        assert "text/html" in (resp.getheader("Content-Type") or "")
        assert "Суток ленты нет" in page
        assert "disabled" in page
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    assert trading_mode() == "off"


def test_http_unknown_contour_meta_is_plain_500(tmp_path: Path) -> None:
    """POST must not leak a traceback. Unknown meta is 500, not a write."""
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.set_meta("contour", "maybe")
    kn.close()
    _hours24_tape(vault.tape)
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            "/api/contour",
            body='{"action":"on"}',
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 500
        assert resp.read() == b"error"
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    kn = open_knowledge(vault, create=False)
    try:
        assert kn.meta("contour") == "maybe"
    finally:
        kn.close()
    assert trading_mode() == "off"
