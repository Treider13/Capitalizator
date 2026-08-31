"""Laptop console: read-only, empty honest, no advice, no signer."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path

import pytest

import capitalizator.ops.console as console_pkg
from capitalizator.ops.console import ConsoleApp, _handler, desk_snapshot, render_html
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_empty_snapshot_is_honest(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    snap = desk_snapshot(vault)
    assert snap["trading_mode"] == "off"
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
