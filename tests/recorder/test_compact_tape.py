"""Hourly parts → one file per hour; old live feeds pruned; current hours untouched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from capitalizator.ops.compact_tape import compact
from capitalizator.recorder.sink_parquet import BufferedParquetSink
from capitalizator.types import MarketEvent


def _ev(ts: datetime, i: int) -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts, recv_ts=ts,
                       seq=i, payload={"px": str(i), "qty": "1", "side": "sell"})


def test_compact_merges_old_hours_only_and_prunes_old_live(tmp_path: Path) -> None:
    now = datetime(2026, 9, 3, 12, 30, tzinfo=UTC)
    sink = BufferedParquetSink(tmp_path, flush_every_s=60, max_rows=10_000, live_jsonl=True)
    old = now - timedelta(hours=5)
    for i in range(5):  # five parts in the old hour (write out of order to test sorting)
        sink.write(_ev(old + timedelta(seconds=10 - i), i))
        sink.flush()
    cur = now - timedelta(minutes=5)
    sink.write(_ev(cur, 99))
    sink.flush()
    sink.close()
    old_dir = tmp_path / "bybit" / "BTCUSDT" / "trades" / f"date={old:%Y-%m-%d}"
    cur_dir = tmp_path / "bybit" / "BTCUSDT" / "trades" / f"date={cur:%Y-%m-%d}"
    assert len(list(old_dir.glob("hour=07.*.parquet"))) == 5
    # the old hour's live feed is < 48h → kept; make one that is older to test pruning
    stale = old_dir / "hour=01.jsonl"
    stale.write_text("{}\n")
    older_day = tmp_path / "bybit" / "BTCUSDT" / "trades" / f"date={(now - timedelta(days=3)):%Y-%m-%d}"
    older_day.mkdir(parents=True)
    (older_day / "hour=03.jsonl").write_text("{}\n")
    out = compact(tmp_path, now=now, min_age_h=2, jsonl_keep_h=48)
    assert out["hours_merged"] == 1 and out["parts_removed"] == 5 and out["rows"] == 5
    merged = old_dir / "hour=07.parquet"
    assert merged.exists() and not list(old_dir.glob("hour=07.*.parquet"))
    table = pq.read_table(merged)
    assert [r for r in table.column("seq").to_pylist()] == [4, 3, 2, 1, 0]  # sorted by exchange_ts
    assert len(list(cur_dir.glob("hour=12.*.parquet"))) == 1  # current hour untouched
    assert (cur_dir / "hour=12.jsonl").exists() and (old_dir / "hour=07.jsonl").exists()
    assert not (older_day / "hour=03.jsonl").exists() and out["live_removed"] == 1
    # idempotent
    assert compact(tmp_path, now=now)["hours_merged"] == 0
