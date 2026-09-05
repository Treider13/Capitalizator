"""Vault backfill writes holes, leaves r_net, second pass is a no-op."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from capitalizator.hyexec.backfill import backfill_vault, days_for_holes, main
from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.hyexec.tape_day import load_trade_events
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink, _row, live_row, partition_path
from capitalizator.types import MarketEvent

AS_OF = datetime(2026, 9, 1, 10, 5, tzinfo=UTC)


def _hole() -> dict:
    row = {key: None for key in FEATURE_KEYS}
    row["touch_id"] = "t1"
    row["symbol"] = "BTCUSDT"
    row["touch_ts"] = AS_OF.isoformat()
    row["paper"] = {"shadow": {"filled": True, "r_net": "2.5"}}
    return row


def test_backfill_vault_from_trade_tape(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    try:
        knowledge.put_journal_touch("t1", _hole())
    finally:
        knowledge.close()
    sink = ParquetSink(vault.tape)
    for i in range(3):
        ts = AS_OF - timedelta(minutes=2 - i)
        sink.write(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                payload={"px": str(100 + i), "qty": "1", "side": "buy"},
            )
        )
    first = backfill_vault(vault)
    assert first["filled"] >= 1
    knowledge = open_knowledge(vault)
    try:
        row = knowledge.journal_rows()[0]
    finally:
        knowledge.close()
    assert row["paper"]["shadow"]["r_net"] == "2.5"
    assert any(row.get(k) not in {None, "", "null", "none"} for k in FEATURE_KEYS)
    second = backfill_vault(vault)
    assert second["filled"] == 0
    assert main(["--userdir", str(vault.root)]) == 0


def test_load_trade_events_reads_live_jsonl(tmp_path: Path) -> None:
    tape = tmp_path / "tape"
    tape.mkdir()
    event = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=AS_OF,
        recv_ts=AS_OF,
        payload={"px": "100", "qty": "1", "side": "buy"},
    )
    path = partition_path(tape, event).with_suffix(".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(live_row(_row(event)), separators=(",", ":")) + "\n")
    got = load_trade_events(tape, symbols={"BTCUSDT"})
    assert len(got) == 1
    assert got[0].payload["px"] == "100"
    assert load_trade_events(tape, symbols={"ETHUSDT"}) == []


def test_days_for_holes_matches_live_recent_days() -> None:
    from capitalizator.desk.tape import TapeCursor

    hole = {key: None for key in FEATURE_KEYS}
    hole["touch_id"] = "t1"
    hole["touch_ts"] = AS_OF.isoformat()
    days = days_for_holes([hole])
    assert AS_OF.date().isoformat() in days
    assert len(days) == TapeCursor.RECENT_DAYS + 1


def test_load_trade_events_days_skips_other_dates(tmp_path: Path) -> None:
    tape = tmp_path / "tape"
    tape.mkdir()
    sink = ParquetSink(tape)
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=AS_OF,
            recv_ts=AS_OF,
            payload={"px": "100", "qty": "1", "side": "buy"},
        )
    )
    old = AS_OF.replace(month=8, day=1)
    sink.write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=old,
            recv_ts=old,
            payload={"px": "1", "qty": "1", "side": "buy"},
        )
    )
    got = load_trade_events(tape, symbols={"BTCUSDT"}, days={"2026-09-01"})
    assert len(got) == 1
    assert got[0].payload["px"] == "100"
