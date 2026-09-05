"""Tape Desk chrome: glossary page, shared tabs, no advice, no order ticket."""

from __future__ import annotations

from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

from capitalizator.ops.console import VENDOR_TYPES, ConsoleApp, _handler, render_html, vendor_file
from capitalizator.ops.daily_map_report import contains_advice
from capitalizator.ops.desk_chrome import render_glossary_html
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_glossary_html_has_real_terms_and_no_advice() -> None:
    page = render_glossary_html()
    assert "ACCORD" in page and "СОГЛАСИЕ" in page
    assert "найти код" in page
    assert contains_advice(page) is False
    assert 'href="/glossary?group=' in page
    filtered = render_glossary_html(group="ЖЮРИ")
    assert "ACCORD" in filtered
    assert "<td class='mono'>DEFEND</td>" not in filtered


def test_vendor_engines_are_allowlisted() -> None:
    for name in VENDOR_TYPES:
        got = vendor_file(name)
        assert got is not None
        data, ctype = got
        assert data.startswith(b"/*!")
        assert "javascript" in ctype
    assert vendor_file("../chronos.html") is None
    assert vendor_file("nope.js") is None
    assert vendor_file("") is None


def test_desk_html_has_tape_desk_chrome_and_live_controls(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    page = render_html(vault)
    assert "Tape Desk" in page
    assert 'href="/glossary"' in page
    assert 'id="replay-play"' in page
    assert 'id="book-imbalance"' in page
    assert 'src="/vendor/lightweight-charts.standalone.production.js"' in page
    assert 'src="/vendor/gsap.min.js"' in page
    assert 'src="/vendor/pixi.min.js"' in page
    assert 'class="status-lock"' in page
    assert "заявка закрыта" not in page
    assert contains_advice(page) is False


def test_glossary_route_is_html_api_stays_json(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/glossary")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode()
        conn.close()
        assert "text/html" in (resp.getheader("Content-Type") or "") or "<html" in body
        assert "СОГЛАСИЕ" in body
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/glossary")
        resp = conn.getresponse()
        assert resp.status == 200
        raw = resp.read().decode()
        conn.close()
        assert '"terms"' in raw and "ACCORD" in raw
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/ops")
        assert "Tape Desk" in conn.getresponse().read().decode()
        conn.close()
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/settings")
        settings = conn.getresponse().read().decode()
        conn.close()
        assert "1. Сохранить ключ" in settings
        assert "2. Проверить ключ на бирже" in settings
        assert "action='/mode'" in settings
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/touch")
        touch = conn.getresponse().read().decode()
        conn.close()
        assert "ордеров нет" in touch
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/vendor/gsap.min.js")
        gsap = conn.getresponse()
        gsap_body = gsap.read()
        conn.close()
        assert gsap.status == 200
        assert "javascript" in (gsap.getheader("Content-Type") or "")
        assert gsap_body.startswith(b"/*!") and b"GSAP" in gsap_body[:80]
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/vendor/lightweight-charts.standalone.production.js")
        assert conn.getresponse().status == 200
        conn.close()
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/vendor/pixi.min.js")
        assert conn.getresponse().status == 200
        conn.close()
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/vendor/../chronos.html")
        assert conn.getresponse().status == 404
        conn.close()
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/vendor/nope.js")
        assert conn.getresponse().status == 404
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
