"""GET /api/news is CSV ∪ intel surprises plus an intel heartbeat."""

from __future__ import annotations

from datetime import UTC, datetime
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

from capitalizator.card.live import CardLive, VolumeSnapshot
from capitalizator.ops.console import ConsoleApp, _handler
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import Vault, init_vault

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def _serve(vault: Vault) -> tuple[HTTPServer, Thread, str, int]:
    app = ConsoleApp(vault)
    httpd = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, thread, str(host), int(port)


def _json_get(host: str, port: int, path: str) -> dict:
    conn = HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    import json

    assert resp.status == 200, body
    return json.loads(body)


def test_api_news_csv_and_hack_share_origin(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_intel_item(
        "rss-hack",
        kind="rss",
        source_id="rss:https://announce.bybit.com",
        known_at=datetime.now(tz=UTC).isoformat(),
        payload={"text": "Hot wallet hack", "event_class": "HACK", "url": "https://announce.bybit.com"},
    )
    kn.set_meta("intel_heartbeat", NOW.isoformat())
    kn.close()
    httpd, thread, host, port = _serve(vault)
    try:
        news = _json_get(host, port, "/api/news")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    classes = {row["class"] for row in news["events"]}
    assert {"CPI", "FOMC", "NFP", "PCE", "HACK"} <= classes
    hack = next(row for row in news["events"] if row["class"] == "HACK")
    assert hack["origin"] == "intel"
    cpi = next(row for row in news["events"] if row["class"] == "CPI")
    assert cpi["origin"] == "csv"
    assert news["every_s"] == 300
    assert news["stale"] is True or news["stale"] is False


def test_api_news_missing_heartbeat_is_stale_not_quiet(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    httpd, thread, host, port = _serve(vault)
    try:
        news = _json_get(host, port, "/api/news")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    assert news["events"]
    assert news["stale"] is True
    assert news["intel_heartbeat"] is None
    assert news["heartbeat_age_s"] is None
    assert news["card_status"] == "no card"
    assert news["card_status_label"]
    assert "no card" in news["card_status_label"]


def test_api_news_fresh_heartbeat_is_not_stale(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.set_meta("intel_heartbeat", datetime.now(tz=UTC).isoformat())
    kn.close()
    httpd, thread, host, port = _serve(vault)
    try:
        news = _json_get(host, port, "/api/news")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    assert news["stale"] is False
    assert news["heartbeat_age_s"] is not None
    assert news["heartbeat_age_s"] <= 900


def test_chronos_html_mentions_intel_stale() -> None:
    html = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "ops" / "chronos.html"
    text = html.read_text(encoding="utf-8")
    assert "intel:stale" in text
    assert "n.origin" in text
    assert "card_status" in text
    assert "no card" in text
    assert "/api/news?symbol=" in text


def _card(*, known_at: datetime) -> CardLive:
    return CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=known_at,
        fib_zone="OTE",
        fib_level="0.718",
        rsi_htf="52",
        gex_bg="+2.1M",
        fvg_status="filled",
        sweep_status="done",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
        volume=VolumeSnapshot(rvol="2.3", poc="100", vah="101", val="99"),
    )


def test_api_news_card_status_is_per_symbol(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_card_live("BTCUSDT", _card(known_at=datetime.now(tz=UTC)).to_payload())
    kn.close()
    httpd, thread, host, port = _serve(vault)
    try:
        btc = _json_get(host, port, "/api/news?symbol=BTCUSDT")
        eth = _json_get(host, port, "/api/news?symbol=ETHUSDT")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    assert btc["card_status"] == "fresh"
    assert btc["card_status_label"] is None
    assert eth["card_status"] == "no card"


def test_api_news_stale_card_uses_touch_token(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_card_live("BTCUSDT", _card(known_at=NOW).to_payload())
    kn.close()
    httpd, thread, host, port = _serve(vault)
    try:
        news = _json_get(host, port, "/api/news?symbol=BTCUSDT")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    assert news["card_status"] == "stale"
    assert "stale" in news["card_status_label"]


def test_api_news_corrupt_card_is_not_500(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    kn.put_card_live("BTCUSDT", {"symbol": "BTCUSDT", "bearing_verdict": "propose"})
    kn.close()
    httpd, thread, host, port = _serve(vault)
    try:
        news = _json_get(host, port, "/api/news?symbol=BTCUSDT")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
    assert news["card_status"] == "no card"
    assert news["events"]
