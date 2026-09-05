"""Vault backfill writes holes, leaves r_net, second pass is a no-op."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from capitalizator.hyexec.backfill import backfill_vault, main
from capitalizator.hyexec.dataset import FEATURE_KEYS
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
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
