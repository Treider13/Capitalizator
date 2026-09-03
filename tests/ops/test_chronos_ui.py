"""Э8: chronos is clickable — symbol, TF, zones, paper stats, replay, two knobs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

from capitalizator.exec.replay import ReplayEngine
from capitalizator.ops.chronos_data import replay_for
from capitalizator.ops.console import ConsoleApp, _handler
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent

HTML = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "ops" / "chronos.html"
NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_chronos_has_desk_controls() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="symbol"' in text
    assert 'data-tf="15m"' in text
    assert 'data-tf="1h"' in text
    assert 'data-tf="4h"' in text
    assert 'data-tf="1d"' in text
    assert 'id="replay-bars"' in text
    assert 'id="replay-book"' in text
    assert "/api/replay" in text
    assert "/api/paper" in text
    assert 'id="paper-stats"' in text
    assert 'id="knobs"' in text
    assert "symbol = (st.symbols && st.symbols[0]) || symbol" not in text
    assert "&tf=\" + encodeURIComponent(tf)" in text


def test_replay_events_two_runs_match() -> None:
    evs = [
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=1,
            payload={"bids": [["100", "5"]], "asks": [["100.2", "5"]]},
        ),
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=2,
            payload={"bids": [["100", "8"]], "asks": []},
        ),
    ]
    a = ReplayEngine().run_events(evs)
    b = ReplayEngine().run_events(evs)
    assert a == b
    assert len(a) == 2
    assert a[0].best() != a[1].best()


def test_replay_api_empty_and_tape(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    empty = replay_for(vault, symbol="BTCUSDT")
    assert empty["n"] == 0 and empty["ok"] is True
    sink = ParquetSink(vault.tape)
    sink.write(
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=1,
            payload={"bids": [["100", "5"]], "asks": [["100.2", "5"]]},
        )
    )
    sink.flush()
    got = replay_for(vault, symbol="BTCUSDT")
    assert got["n"] == 1 and got["ok"] is True
    assert got["last_bid"] == "100"
    app = ConsoleApp(vault)
    server = HTTPServer(("127.0.0.1", 0), _handler(app))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/replay?symbol=BTCUSDT")
        resp = conn.getresponse()
        assert resp.status == 200
        body = json.loads(resp.read().decode())
        conn.close()
        assert body["n"] == 1
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/api/bars?symbol=BTCUSDT&tf=1h&limit=10")
        bars = json.loads(conn.getresponse().read().decode())
        conn.close()
        assert bars["tf"] == "1h"
        assert bars["bars"] == []
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/")
        page = conn.getresponse().read().decode()
        conn.close()
        assert 'id="symbol"' in page
        assert 'id="knobs"' in page
        assert 'id="paper-stats"' in page
    finally:
        server.shutdown()
        server.server_close()
