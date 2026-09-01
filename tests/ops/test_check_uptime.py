"""Uptime checker on fixtures. Does not claim a live 24h."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from capitalizator.ops.check_uptime import check_uptime, load_events, main
from capitalizator.recorder.sink_parquet import SCHEMA, ParquetSink
from capitalizator.types import MarketEvent


def _trade(second: int, *, symbol: str = "BTCUSDT") -> MarketEvent:
    ts = datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC) + timedelta(seconds=second)
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": "1", "qty": "0.001", "side": "buy"},
    )


def _gap(
    start_s: int, end_s: int, *, in_payload: bool = True, symbol: str = "BTCUSDT"
) -> MarketEvent:
    start = datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC) + timedelta(seconds=start_s)
    end = datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC) + timedelta(seconds=end_s)
    payload: dict = {"missing_stream": "trades", "seq_from": 0, "seq_to": 0}
    if in_payload:
        payload["ts_from"] = start.isoformat()
        payload["ts_to"] = end.isoformat()
    return MarketEvent(
        stream="gap",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=start,
        recv_ts=end,
        seq=None,
        payload=payload,
    )


def test_contiguous_hour_passes() -> None:
    events = [_trade(s) for s in range(0, 3601)]
    span = check_uptime(events, hours=1, max_unmarked_gap_s=1, symbol="BTCUSDT")
    assert span == 3600


def test_unmarked_hole_fails() -> None:
    events = [_trade(0), _trade(1), _trade(120)]
    with pytest.raises(SystemExit, match="unmarked gap"):
        check_uptime(events, hours=120 / 3600, max_unmarked_gap_s=10, symbol="BTCUSDT")


def test_marked_hole_passes() -> None:
    events = [_trade(0), _trade(120), _gap(0, 120)]
    span = check_uptime(events, hours=120 / 3600, max_unmarked_gap_s=10, symbol="BTCUSDT")
    assert span == 120


def test_seq_gap_without_time_range_does_not_cover_silence() -> None:
    """GapDetector timestamps are 'noticed at', often 1s apart — not the hole."""
    events = [_trade(0), _trade(120), _gap(0, 120, in_payload=False)]
    with pytest.raises(SystemExit, match="unmarked gap"):
        check_uptime(events, hours=120 / 3600, max_unmarked_gap_s=10, symbol="BTCUSDT")


def test_naive_gap_clock_does_not_cover() -> None:
    """Naive ts_from is not a cover. Same as a seq-gap without a time range."""
    start = datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=120)
    gap = MarketEvent(
        stream="gap",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=start,
        recv_ts=end,
        seq=None,
        payload={
            "ts_from": start.replace(tzinfo=None).isoformat(),
            "ts_to": end.replace(tzinfo=None).isoformat(),
        },
    )
    with pytest.raises(SystemExit, match="unmarked gap"):
        check_uptime(
            [_trade(0), _trade(120), gap],
            hours=120 / 3600,
            max_unmarked_gap_s=10,
            symbol="BTCUSDT",
        )


def test_other_symbol_gap_does_not_cover() -> None:
    """An ETH gap must not mark a BTC hole. hours24 inherits this law."""
    events = [_trade(0), _trade(120), _gap(0, 120, symbol="ETHUSDT")]
    with pytest.raises(SystemExit, match="unmarked gap"):
        check_uptime(events, hours=120 / 3600, max_unmarked_gap_s=10, symbol="BTCUSDT")


def test_short_span_fails() -> None:
    events = [_trade(0), _trade(10)]
    with pytest.raises(SystemExit, match="span"):
        check_uptime(events, hours=1, max_unmarked_gap_s=10, symbol="BTCUSDT")


def test_load_events_skips_other_symbol_rows(tmp_path: Path) -> None:
    """A BTCUSDT path must not feed ETH rows into hours24."""
    dest = tmp_path / "BTCUSDT" / "mixed.parquet"
    dest.parent.mkdir(parents=True)
    start = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    end = start + timedelta(seconds=120)
    table = pa.Table.from_pylist(
        [
            {
                "stream": "trades",
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "exchange_ts": start,
                "recv_ts": start,
                "seq": None,
                "payload_json": '{"px":"1","qty":"0.001","side":"buy"}',
            },
            {
                "stream": "trades",
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "exchange_ts": end,
                "recv_ts": end,
                "seq": None,
                "payload_json": '{"px":"1","qty":"0.001","side":"buy"}',
            },
            {
                "stream": "gap",
                "exchange": "bybit",
                "symbol": "ETHUSDT",
                "exchange_ts": start,
                "recv_ts": end,
                "seq": None,
                "payload_json": (
                    f'{{"ts_from":"{start.isoformat()}","ts_to":"{end.isoformat()}"}}'
                ),
            },
        ],
        schema=SCHEMA,
    )
    pq.write_table(table, dest)
    loaded = load_events(tmp_path, symbol="BTCUSDT")
    assert [e.symbol for e in loaded] == ["BTCUSDT", "BTCUSDT"]
    assert all(e.stream == "trades" for e in loaded)
    with pytest.raises(SystemExit, match="unmarked gap"):
        check_uptime(loaded, hours=120 / 3600, max_unmarked_gap_s=10, symbol="BTCUSDT")


def test_cli_reads_parquet(tmp_path: Path) -> None:
    sink = ParquetSink(tmp_path)
    for ev in [_trade(s) for s in range(0, 61)]:
        sink.write(ev)
    assert main(
        [
            "--data-root",
            str(tmp_path),
            "--symbol",
            "BTCUSDT",
            "--hours",
            str(60 / 3600),
            "--max-unmarked-gap-s",
            "1",
        ]
    ) == 0
    loaded = load_events(tmp_path, symbol="BTCUSDT")
    assert len(loaded) == 61


def test_cli_universe_requires_each_symbol(tmp_path: Path) -> None:
    sink = ParquetSink(tmp_path)
    for ev in [_trade(s) for s in range(0, 61)]:
        sink.write(ev)
    for ev in [_trade(s, symbol="ETHUSDT") for s in range(0, 61)]:
        sink.write(ev)
    uni = tmp_path / "universe.yaml"
    uni.write_text(
        "exchange: bybit\ncategory: linear\nsymbols: [BTCUSDT, ETHUSDT]\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--data-root",
                str(tmp_path),
                "--universe",
                str(uni),
                "--hours",
                str(60 / 3600),
                "--max-unmarked-gap-s",
                "1",
            ]
        )
        == 0
    )


def test_cli_universe_fails_if_eth_missing(tmp_path: Path) -> None:
    sink = ParquetSink(tmp_path)
    for ev in [_trade(s) for s in range(0, 61)]:
        sink.write(ev)
    uni = tmp_path / "universe.yaml"
    uni.write_text(
        "exchange: bybit\ncategory: linear\nsymbols: [BTCUSDT, ETHUSDT]\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="need at least two trades"):
        main(
            [
                "--data-root",
                str(tmp_path),
                "--universe",
                str(uni),
                "--hours",
                str(60 / 3600),
                "--max-unmarked-gap-s",
                "1",
            ]
        )
