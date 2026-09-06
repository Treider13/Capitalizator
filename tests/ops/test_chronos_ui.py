"""Э8: chronos is clickable — symbol, TF, zones, paper stats, replay, two knobs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from capitalizator.desk.tape import event_from_jsonl_line
from capitalizator.exec.replay import ReplayEngine
from capitalizator.ops.chronos_data import _load_symbol_stream, last_prices, replay_for
from capitalizator.ops.console import ConsoleApp, _handler
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import BufferedParquetSink, ParquetSink
from capitalizator.types import MarketEvent

HTML = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "ops" / "chronos.html"
NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_chronos_has_desk_controls() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="symbol"' in text
    assert 'data-tf="1m"' in text
    assert 'data-tf="5m"' in text
    assert 'data-tf="15m"' in text
    assert 'data-tf="1h"' in text
    assert 'data-tf="4h"' in text
    assert 'data-tf="1d"' in text
    assert 'data-tf="3m"' not in text
    assert "function loadBars()" in text
    assert "function tickTape()" in text
    assert "function refreshSoon()" in text
    assert "setInterval(tickTape, 400)" in text
    assert "setInterval(refresh, 30000)" in text
    assert "candleSeries.update" in text
    assert "/api/tape" in text
    assert 'id="replay-bars"' in text
    assert 'id="replay-book"' in text
    assert "/api/replay" in text
    assert "/api/paper" in text
    assert 'id="paper-stats"' in text
    assert 'id="knobs"' in text
    assert "symbol = (st.symbols && st.symbols[0]) || symbol" not in text
    assert "&tf=\" + encodeURIComponent(tf)" in text
    assert 'src="/vendor/lightweight-charts.standalone.production.js"' in text
    assert 'src="/vendor/gsap.min.js"' in text
    assert 'src="/vendor/pixi.min.js"' in text


def test_load_symbol_stream_ignores_other_symbols(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    sink = ParquetSink(vault.tape)
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100", "qty": "1", "side": "buy"},
        )
    )
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="ETHUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "200", "qty": "1", "side": "buy"},
        )
    )
    events = _load_symbol_stream(vault.tape, symbol="BTCUSDT", stream="trades")
    assert [event.symbol for event in events] == ["BTCUSDT"]
    assert events[0].payload["px"] == "100"


def test_last_prices_does_not_scan_tape(tmp_path: Path) -> None:
    """Empty sqlite must not open gigabytes of parquet just to paint a price."""
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    knowledge.close()
    ParquetSink(vault.tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100.4", "qty": "1", "side": "buy"},
        )
    )
    assert last_prices(vault) == {}
    knowledge = open_knowledge(vault)
    knowledge.put_last_price("BTCUSDT", "100.4")
    knowledge.close()
    assert last_prices(vault) == {"BTCUSDT": "100.4"}


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
            payload={"bids": [["100", "0"], ["99.8", "5"]], "asks": []},
        ),
    ]
    a = ReplayEngine().run_events(evs)
    b = ReplayEngine().run_events(evs)
    assert a == b
    assert len(a) == 2
    assert a[0].best() != a[1].best()


def test_event_from_jsonl_line_skips_garbage() -> None:
    assert event_from_jsonl_line("") is None
    assert event_from_jsonl_line("{") is None
    assert event_from_jsonl_line("{}") is None


def test_run_events_empty_is_empty() -> None:
    assert ReplayEngine().run_events([]) == []


def test_run_events_bad_level_raises() -> None:
    evs = [
        MarketEvent(
            stream="snapshot",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=1,
            payload={"bids": [["100"]], "asks": [["100.2", "5"]]},
        )
    ]
    with pytest.raises(ValueError, match="level must be"):
        ReplayEngine().run_events(evs)


def test_run_events_gap_does_not_invent() -> None:
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
            seq=3,
            payload={"bids": [["99.8", "5"]], "asks": []},
        ),
    ]
    cps = ReplayEngine().run_events(evs)
    assert cps[-1].seq == 3
    assert cps[-1].best_bid == Decimal("100")


def test_replay_api_empty_and_tape(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    empty = replay_for(vault, symbol="BTCUSDT")
    assert empty["n"] == 0 and empty["ok"] is True
    ParquetSink(vault.tape).write(
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
        assert "бумага (все)" not in page
    finally:
        server.shutdown()
        server.server_close()


def test_replay_same_ts_orders_snapshot_before_diff(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
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
    sink.write(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=2,
            payload={"bids": [["100", "0"], ["99.8", "5"]], "asks": []},
        )
    )
    got = replay_for(vault, symbol="BTCUSDT")
    assert got["ok"] is True
    assert got["n"] == 2
    assert got["last_bid"] == "99.8"


def test_replay_reads_live_jsonl_and_does_not_double_count(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    live = BufferedParquetSink(
        vault.tape, flush_every_s=60, max_rows=10_000, live_jsonl=True
    )
    ev = MarketEvent(
        stream="snapshot",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=NOW,
        recv_ts=NOW,
        seq=1,
        payload={"bids": [["100", "5"]], "asks": [["100.2", "5"]]},
    )
    live.write(ev)
    live.close()
    only_jsonl = replay_for(vault, symbol="BTCUSDT")
    assert only_jsonl["n"] == 1 and only_jsonl["ok"] is True
    assert only_jsonl["last_bid"] == "100"
    flushed = BufferedParquetSink(
        vault.tape, flush_every_s=60, max_rows=1, live_jsonl=True
    )
    flushed.write(
        MarketEvent(
            stream="book_diff",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            seq=2,
            payload={"bids": [["100", "0"], ["99.8", "5"]], "asks": []},
        )
    )
    flushed.close()
    both = replay_for(vault, symbol="BTCUSDT")
    assert both["ok"] is True
    assert both["n"] == 2
    assert both["last_bid"] == "99.8"


def test_hour_files_for_htf_is_more_than_four_daily_candles() -> None:
    from capitalizator.ops.chronos_data import _hour_files_for

    assert _hour_files_for("1m", 200) == 24
    assert _hour_files_for("15m", 200) == 52
    assert _hour_files_for("1d", 200) == 24 * 21
    assert _hour_files_for("4h", 200) == 24 * 21


def test_bars_for_reads_live_jsonl_and_forming(tmp_path: Path) -> None:
    from capitalizator.ops.chronos_data import bars_for

    vault = init_vault(tmp_path / "desk")
    open_knowledge(vault).close()
    now = datetime(2026, 9, 6, 1, 50, tzinfo=UTC)
    live = BufferedParquetSink(vault.tape, flush_every_s=60, max_rows=10_000, live_jsonl=True)
    live.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=now - timedelta(minutes=18),
            recv_ts=now - timedelta(minutes=18),
            payload={"px": "79500", "qty": "1", "side": "sell"},
        )
    )
    live.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=now - timedelta(minutes=2),
            recv_ts=now - timedelta(minutes=2),
            payload={"px": "79591.6", "qty": "1", "side": "buy"},
        )
    )
    rows = bars_for(vault, symbol="BTCUSDT", tf="15m", now=now)
    live.close()
    closed = [row for row in rows if not row.get("forming")]
    forming = [row for row in rows if row.get("forming")]
    assert closed, "closed 15m from jsonl without parquet flush"
    assert forming and forming[0]["close"] == "79591.6"
    assert forming[0]["tf"] == "15m"


def test_tape_tick_has_book_and_forming(tmp_path: Path) -> None:
    from capitalizator.ops.chronos_data import tape_tick

    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    knowledge.put_last_price("BTCUSDT", "79591.6")
    knowledge.put_book_levels(
        "BTCUSDT",
        {"symbol": "BTCUSDT", "bids": [["79591.5", "2"]], "asks": [["79591.7", "3"]], "ts": "t"},
    )
    knowledge.close()
    live = BufferedParquetSink(vault.tape, flush_every_s=60, max_rows=10_000, live_jsonl=True)
    live.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=datetime.now(tz=UTC),
            recv_ts=datetime.now(tz=UTC),
            payload={"px": "79591.6", "qty": "1", "side": "buy"},
        )
    )
    got = tape_tick(vault, symbol="BTCUSDT", tf="1m")
    live.close()
    assert got["tf"] == "1m"
    assert got["last_price"] == "79591.6"
    assert got["book"]["bids"][0][0] == "79591.5"
    assert got["trades"]
    assert got["forming"] is not None
    assert got["forming"]["forming"] is True
    assert got["forming"]["close"] == "79591.6"
