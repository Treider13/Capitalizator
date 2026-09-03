"""Laptop console: GET plus contour POST. No orders. No signer."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
        assert '<button type="submit">Включить контур</button>' not in page
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


def test_chronos_api_empty_shapes(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        paths = [
            "/api/bars?symbol=BTCUSDT&tf=15m&limit=10",
            "/api/zones?symbol=BTCUSDT",
            "/api/book?symbol=BTCUSDT",
            "/api/trades?symbol=BTCUSDT&limit=5",
            "/api/touch/latest?symbol=BTCUSDT",
            "/api/dashboard",
            "/api/news",
            "/api/authors",
            "/api/llm_summary",
            "/api/gates",
            "/api/hello/status",
        ]
        for path in paths:
            conn = HTTPConnection(host, port, timeout=3)
            conn.request("GET", path)
            resp = conn.getresponse()
            assert resp.status == 200, path
            payload = json.loads(resp.read().decode())
            assert isinstance(payload, dict), path
            blob = json.dumps(payload, ensure_ascii=False).lower()
            for word in ("лонг", "шорт", "купи", "продай", "завтра"):
                assert word not in blob
            conn.close()
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/status")
        status = json.loads(conn.getresponse().read().decode())
        conn.close()
        assert "last_price" in status
        assert status["session_window"]["start"] == "16:30"
        assert status["last_jury"] == {}
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/hello/status")
        hello = json.loads(conn.getresponse().read().decode())
        conn.close()
        assert hello == {"hello_ok": False, "real": False, "cred_present": False}
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/bars?symbol=BTCUSDT")
        bars = json.loads(conn.getresponse().read().decode())
        conn.close()
        assert bars["bars"] == []
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/touch/latest")
        touch = json.loads(conn.getresponse().read().decode())
        conn.close()
        assert touch["touch"] is None
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/")
        page = conn.getresponse().read().decode()
        conn.close()
        assert "ХРОНОС" in page
        assert "Касаний нет" in page
        assert 'id="contour-box"' in page
        assert "fib / rsi / fvg / sweep / gex" in page
    finally:
        server.shutdown()
        server.server_close()


def _json_get(host: str, port: int, path: str) -> dict:
    conn = HTTPConnection(host, port, timeout=3)
    conn.request("GET", path)
    resp = conn.getresponse()
    assert resp.status == 200, path
    payload = json.loads(resp.read().decode())
    conn.close()
    return payload


def test_chronos_api_reads_vault_not_examples(tmp_path: Path) -> None:
    """Seeded parquet + journal must surface as-is. A second tape must differ."""
    from capitalizator.book.reconstruct import Book
    from capitalizator.desk.loop import DeskLoop
    from capitalizator.recorder.rest_snapshot import BookSnapshot
    from capitalizator.zones.model import Bar, Zone

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    created = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    window = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=created,
    )
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=window,
            seq=1,
            bids=(("100.4", "20"),),
            asks=(("100.6", "20"),),
        )
    )
    trade = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=window,
        recv_ts=window,
        payload={"px": "100.4", "qty": "1", "side": "sell"},
    )
    ParquetSink(vault.tape).write(trade)
    ParquetSink(vault.tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=window + timedelta(minutes=20),
            recv_ts=window + timedelta(minutes=20),
            payload={"px": "100.8", "qty": "2", "side": "buy"},
        )
    )
    desk = DeskLoop(knowledge=knowledge, user_mode="off", tick_size=Decimal("0.1"))
    snapshot = MarketEvent(
        stream="snapshot",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=window,
        recv_ts=window,
        seq=1,
        payload={"bids": [["100.4", "20"]], "asks": [["100.6", "20"]]},
    )
    desk.on_event(snapshot)
    desk.on_book("BTCUSDT", book)
    desk.on_event(trade, [zone])
    desk.tick(window + timedelta(seconds=8))
    events = desk.on_bar_close(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=window,
            close_ts=window + timedelta(minutes=15),
            open=Decimal("100.4"),
            high=Decimal("100.6"),
            low=Decimal("99.9"),
            close=Decimal("100.4"),
        )
    )
    touch_id = events[0]["touch_id"]
    journal = knowledge.get_journal_touch(touch_id)
    assert journal is not None
    knowledge.save_report(day="2026-08-31", kind="map", body="Касаний 1. Жюри без совета.")
    knowledge.close()

    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status = _json_get(host, port, "/api/status")
        assert status["last_price"]["BTCUSDT"] == "100.4"
        assert status["last_jury"]["BTCUSDT"]["jury"] == journal["jury"]
        assert status["last_jury"]["BTCUSDT"]["jury"] in {"ACCORD", "SPLIT", "VETO", "SILENCE"}

        trades = _json_get(host, port, "/api/trades?symbol=BTCUSDT&limit=50")
        assert [row["px"] for row in trades["trades"]] == ["100.4", "100.8"]
        assert trades["trades"][-1]["side"] == "buy"

        other = _json_get(host, port, "/api/trades?symbol=ETHUSDT&limit=50")
        assert other["trades"] == []

        bars = _json_get(host, port, "/api/bars?symbol=BTCUSDT&tf=15m&limit=200")
        assert bars["bars"], "closed bars must come from parquet trades"
        assert all(row["symbol"] == "BTCUSDT" for row in bars["bars"])
        eth_bars = _json_get(host, port, "/api/bars?symbol=ETHUSDT&tf=15m&limit=200")
        assert eth_bars["bars"] == []

        book_payload = _json_get(host, port, "/api/book?symbol=BTCUSDT")
        assert book_payload["bids"][0][0] == "100.4"
        assert book_payload["asks"][0][0] == "100.6"
        empty_book = _json_get(host, port, "/api/book?symbol=ETHUSDT")
        assert empty_book["bids"] == []
        assert empty_book["asks"] == []

        zones = _json_get(host, port, "/api/zones?symbol=BTCUSDT")
        assert zones["zones"]
        assert zones["zones"][0]["lo"] == "100"
        assert zones["zones"][0]["hi"] == "101"

        latest = _json_get(host, port, "/api/touch/latest?symbol=BTCUSDT")
        assert latest["touch"] is not None
        assert latest["touch"]["touch_id"] == touch_id
        assert latest["touch"]["jury"] == journal["jury"]
        assert latest["touch"]["cav_label"] == journal["cav_label"]
        assert latest["touch"]["card_id"] == journal["card_id"]
        assert latest["touch"]["claims"]
        missing = _json_get(host, port, "/api/touch/latest?symbol=ETHUSDT")
        assert missing["touch"] is None

        dash = _json_get(host, port, "/api/dashboard")
        assert dash["last_touch"]["touch_id"] == touch_id
        assert dash["last_price"]["BTCUSDT"] == "100.4"

        news = _json_get(host, port, "/api/news")
        classes = {row["class"] for row in news["events"]}
        assert {"CPI", "FOMC", "NFP", "PCE"} <= classes

        authors = _json_get(host, port, "/api/authors")
        assert authors["posts"] == []
        assert authors["sources"] == []

        llm = _json_get(host, port, "/api/llm_summary")
        assert "Касаний 1" in llm["summary"]
        assert llm["trade_advice"] is False

        hello = _json_get(host, port, "/api/hello/status")
        assert hello == {"hello_ok": False, "real": False, "cred_present": False}

        gates = _json_get(host, port, "/api/gates")
        assert gates["n_touches"] == 1
        assert gates["phases"]["f0"]["have"] == 1
        assert gates["phases"]["f0"]["ok"] is False
    finally:
        server.shutdown()
        server.server_close()

    other_vault = init_vault(tmp_path / "other")
    open_knowledge(other_vault).close()
    later = datetime(2026, 8, 31, 16, 0, tzinfo=UTC)
    ParquetSink(other_vault.tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=later,
            recv_ts=later,
            payload={"px": "25000", "qty": "3", "side": "buy"},
        )
    )
    ParquetSink(other_vault.tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=later + timedelta(minutes=20),
            recv_ts=later + timedelta(minutes=20),
            payload={"px": "25100", "qty": "1", "side": "sell"},
        )
    )
    app2 = ConsoleApp(other_vault)
    server2 = HTTPServer(("127.0.0.1", 0), _handler(app2))
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    host2, port2 = server2.server_address[:2]
    try:
        alt = _json_get(host2, port2, "/api/trades?symbol=BTCUSDT&limit=50")
        assert [row["px"] for row in alt["trades"]] == ["25000", "25100"]
        alt_bars = _json_get(host2, port2, "/api/bars?symbol=BTCUSDT&tf=15m&limit=200")
        assert alt_bars["bars"] != bars["bars"]
        alt_touch = _json_get(host2, port2, "/api/touch/latest")
        assert alt_touch["touch"] is None
    finally:
        server2.shutdown()
        server2.server_close()


def _post_json(host: str, port: int, path: str, payload: dict) -> tuple[int, str]:
    conn = HTTPConnection(host, port, timeout=3)
    conn.request(
        "POST",
        path,
        body=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    body = resp.read().decode()
    status = resp.status
    conn.close()
    return status, body


def test_hello_and_live_cred_from_console(tmp_path: Path) -> None:
    from capitalizator.ops.product import hello_recorded, read_user_mode
    from capitalizator.ops.user_keys import cred_present, live_cred_path

    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, body = _post_json(host, port, "/api/mode", {"mode": "demo", "ack": True})
        assert status == 403
        assert body == "hello required"

        status, body = _post_json(host, port, "/api/hello", {"ack": False})
        assert status == 403
        assert body == "ack required"

        status, body = _post_json(host, port, "/api/hello", {"ack": True})
        assert status == 200
        hello = json.loads(body)
        assert hello == {"hello_ok": True, "real": False, "cred_present": False}
        assert hello_recorded(vault) is True

        status, body = _post_json(host, port, "/api/mode", {"mode": "demo", "ack": True})
        assert status == 200
        assert json.loads(body)["user_mode"] == "demo"

        status, body = _post_json(host, port, "/api/mode", {"mode": "live", "ack": True})
        assert status == 403
        assert body == "cred required"
        assert read_user_mode(vault) == "demo"

        status, body = _post_json(host, port, "/api/live-cred", {"ack": True, "id": "", "seed": "s"})
        assert status == 400

        status, body = _post_json(
            host,
            port,
            "/api/live-cred",
            {"ack": True, "id": "pub-id", "seed": "priv-seed"},
        )
        assert status == 200
        saved = json.loads(body)
        assert saved["ok"] is True
        assert saved["cred_present"] is True
        assert saved.get("mode") == "demo"
        assert "priv-seed" not in body
        assert "seed" not in saved
        assert cred_present(vault) is True
        path = live_cred_path(vault)
        assert path.stat().st_mode & 0o077 == 0
        from capitalizator.gateway.keys import load_keys

        keys = load_keys(vault)
        assert keys is not None
        assert keys.api_key == "pub-id"
        assert keys.api_secret == "priv-seed"

        status = _json_get(host, port, "/api/status")
        assert status["hello_ok"] is True
        assert status["cred_present"] is True
        blob = json.dumps(status)
        assert "priv-seed" not in blob
        assert "pub-id" not in blob

        status, body = _post_json(host, port, "/api/mode", {"mode": "live", "ack": True})
        assert status == 200
        assert json.loads(body)["user_mode"] == "live"
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/")
        page = conn.getresponse().read().decode()
        conn.close()
        assert 'id="ready-box"' in page
        assert "priv-seed" not in page
        assert "Как включить стол" in page
        assert "Сохранить ключ" in page
    finally:
        server.shutdown()
        server.server_close()


def test_live_cred_post_is_405_on_wrong_path(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, _body = _post_json(
            host, port, "/api/live-cred/extra", {"ack": True, "id": "a", "seed": "b"}
        )
        assert status == 405
    finally:
        server.shutdown()
        server.server_close()
