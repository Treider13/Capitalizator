"""Replay writes a sandbox journal. Clock is the tape, not the wall. Papers follow."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.hyexec.replay_desk import (
    clock_for,
    follow_open_papers,
    open_paper_n,
    replay_day,
    seed_sandbox,
    zones_from_knowledge,
)
from capitalizator.zones.model import Zone
from capitalizator.hyexec.tape_day import load_day_events
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.sink_parquet import ParquetSink, _row, live_row, partition_path
from capitalizator.types import MarketEvent

DAY = "2026-09-01"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
NEXT = datetime(2026, 9, 2, 13, 0, tzinfo=UTC)


def _event(ts: datetime, px: str, *, side: str = "sell") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "1", "side": side},
    )


def _trade(tape: Path) -> None:
    ParquetSink(tape).write(_event(NOW, "100.4"))


def _write_jsonl(tape: Path, event: MarketEvent) -> Path:
    path = partition_path(tape, event).with_suffix(".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(live_row(_row(event)), separators=(",", ":")) + "\n")
    return path


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
    assert plan["n_open_paper"] == 0
    assert live_rows == []
    assert Path("infra/phase.yaml").read_text(encoding="utf-8") == phase


def test_clock_for_is_last_print_not_wall() -> None:
    ev = [_event(NOW, "100")]
    assert clock_for(ev, DAY) == NOW
    assert clock_for([], DAY) == datetime(2026, 9, 1, 23, 59, 59, tzinfo=UTC)
    later = datetime(2026, 9, 1, 18, 30, tzinfo=UTC)
    assert clock_for([_event(NOW, "1"), _event(later, "2")], DAY) == later


def test_load_day_reads_jsonl_hour_and_skips_that_parquet(tmp_path: Path) -> None:
    tape = tmp_path / "tape"
    tape.mkdir()
    live = _event(NOW, "101.5")
    _write_jsonl(tape, live)
    ParquetSink(tape).write(_event(NOW + timedelta(minutes=1), "99"))
    got = load_day_events(tape, DAY)
    assert len(got) == 1
    assert got[0].payload["px"] == "101.5"
    assert load_day_events(tape, "2026-09-02") == []


def test_follow_closes_open_paper_on_next_day_tape(tmp_path: Path) -> None:
    sand = init_vault(tmp_path / "sand")
    knowledge = open_knowledge(sand)
    knowledge.put_journal_touch(
        "t1",
        {"touch_id": "t1", "symbol": "BTCUSDT", "touch_ts": NOW.isoformat()},
    )
    desk = DeskLoop(knowledge=knowledge, user_mode="learn", tick_size=Decimal("0.1"))
    desk.paper.submit(
        paper_id="p1",
        touch_id="t1",
        symbol="BTCUSDT",
        side="buy",
        limit_px=Decimal("100"),
        qty=Decimal("1"),
        stop=Decimal("90"),
        tp=None,
        tick=Decimal("0.1"),
        now=NOW,
        valid_for=timedelta(hours=1),
        source="shadow",
        tag="bounce",
    )
    pos = desk.paper.positions["p1"]
    pos.state = "open"
    pos.filled_at = NOW
    pos.entry_px = Decimal("100")
    pos.qty_open = Decimal("1")
    assert open_paper_n(desk) == 1
    tape = tmp_path / "tape"
    tape.mkdir()
    ParquetSink(tape).write(_event(NEXT, "89"))
    followed, last = follow_open_papers(desk, tape, DAY)
    assert followed >= 1
    assert last == NEXT
    assert open_paper_n(desk) == 0
    row = knowledge.get_journal_touch("t1")
    assert row is not None
    assert row["paper"]["shadow"]["exit_reason"] == "stop"
    assert row["paper"]["shadow"]["r_net"] is not None
    knowledge.close()


def test_replay_day_without_now_uses_tape_clock(tmp_path: Path) -> None:
    sand = init_vault(tmp_path / "sand")
    tape = tmp_path / "tape"
    tape.mkdir()
    _trade(tape)
    knowledge = open_knowledge(sand)
    try:
        plan = replay_day(tape=tape, knowledge=knowledge, day=DAY)
    finally:
        knowledge.close()
    assert plan["clock"] == NOW.isoformat()
    assert plan["sent"] is False


def test_seed_sandbox_copies_instruments_and_zones_not_journal(tmp_path: Path) -> None:
    live = init_vault(tmp_path / "live")
    sand = init_vault(tmp_path / "sand")
    src = open_knowledge(live)
    dst = open_knowledge(sand)
    zone = Zone.create(
        symbol="SOLUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=NOW,
    )
    try:
        src.set_meta(
            "instruments_snapshot",
            json.dumps(
                {
                    "instruments": {
                        "SOLUSDT": {
                            "symbol": "SOLUSDT",
                            "tick": "0.01",
                            "qty_step": "0.1",
                            "min_qty": "0.1",
                            "min_notional": "5",
                        }
                    }
                }
            ),
        )
        src.put_zone(
            zone.zone_id,
            {
                "zone_id": zone.zone_id,
                "symbol": zone.symbol,
                "tf": zone.tf,
                "side": zone.side,
                "lo": str(zone.lo),
                "hi": str(zone.hi),
                "method": zone.method,
                "created_as_of": zone.created_as_of.isoformat(),
            },
        )
        src.put_journal_touch("live-only", {"touch_id": "live-only", "symbol": "SOLUSDT"})
        got = seed_sandbox(src=src, dst=dst)
        assert got == {"instruments": 1, "zones": 1}
        assert dst.meta("instruments_snapshot") == src.meta("instruments_snapshot")
        assert {row["zone_id"] for row in dst.list_zones()} == {zone.zone_id}
        assert dst.journal_rows() == []
        stored = zones_from_knowledge(dst)
        assert [z.zone_id for z in stored] == [zone.zone_id]
        desk = DeskLoop(knowledge=dst, user_mode="learn")
        assert desk.instrument_ok("SOLUSDT") is True
        for z in stored:
            desk.registry._zones[z.zone_id] = z
        assert zone.zone_id in desk.registry._zones
    finally:
        src.close()
        dst.close()
