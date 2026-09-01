"""§2: desk serve reads parquet tape into the loop. Empty tape is empty."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.desk.__main__ import serve_loop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent

NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_serve_loop_consumes_parquet_trade(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    ParquetSink(vault.tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100.4", "qty": "1", "side": "sell"},
        )
    )
    knowledge = open_knowledge(vault)
    n = {"i": 0}

    def should_stop() -> bool:
        n["i"] += 1
        return n["i"] >= 2

    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=should_stop,
        idle_s=0,
    )
    knowledge.close()
    assert desk.state_for("BTCUSDT").trades
    assert desk.state_for("BTCUSDT").trades[0].payload["px"] == "100.4"


def test_empty_tape_does_not_invent(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    knowledge = open_knowledge(vault)
    n = {"i": 0}
    desk = serve_loop(
        vault=vault,
        knowledge=knowledge,
        should_stop=lambda: (n.update(i=n["i"] + 1) or n["i"] >= 1),
        idle_s=0,
    )
    knowledge.close()
    assert desk.symbols == {}
