from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.ops.check_parquet_count import count_rows, main
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent


def test_count_matches_and_cli(tmp_path: Path) -> None:
    sink = ParquetSink(tmp_path)
    ev = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
        recv_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
        seq=None,
        payload={"px": "1", "qty": "1", "side": "buy"},
    )
    path = sink.write(ev)
    sink.write(ev)
    assert count_rows(path) == 2
    assert main(["--path", str(path), "--expect", "2"]) == 0
    with pytest.raises(SystemExit, match="row count"):
        main(["--path", str(path), "--expect", "3"])
