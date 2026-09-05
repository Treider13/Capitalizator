"""One-day replay writes a sandbox journal. It does not send and does not touch phase.yaml."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.hyexec.replay_desk import replay_day
from capitalizator.hyexec.tape_day import load_day_events
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink
from capitalizator.types import MarketEvent

DAY = "2026-09-01"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _trade(tape: Path) -> None:
    ParquetSink(tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=NOW,
            recv_ts=NOW,
            payload={"px": "100.4", "qty": "1", "side": "sell"},
        )
    )


def test_load_day_skips_other_dates(tmp_path: Path) -> None:
    tape = tmp_path / "tape"
    tape.mkdir()
    _trade(tape)
    ParquetSink(tape).write(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
            recv_ts=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
            payload={"px": "90", "qty": "1", "side": "buy"},
        )
    )
    got = load_day_events(tape, DAY)
    assert len(got) == 1
    assert got[0].payload["px"] == "100.4"
    assert load_day_events(tape, "2026-09-02") == []


def test_replay_day_is_learn_and_does_not_write_phase(tmp_path: Path) -> None:
    live = init_vault(tmp_path / "live")
    sand = init_vault(tmp_path / "sand")
    _trade(live.tape)
    phase = Path("infra/phase.yaml").read_text(encoding="utf-8")
    knowledge = open_knowledge(sand)
    try:
        plan = replay_day(
            tape=live.tape,
            knowledge=knowledge,
            day=DAY,
            now=NOW,
        )
        live_rows = open_knowledge(live).journal_rows()
    finally:
        knowledge.close()
    assert plan["user_mode"] == "learn"
    assert plan["sent"] is False
    assert plan["n_events"] == 1
    assert live_rows == []
    assert Path("infra/phase.yaml").read_text(encoding="utf-8") == phase
