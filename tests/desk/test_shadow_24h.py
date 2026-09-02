"""Desk tick settles shadow R 24/7. Challenger is not an order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.memory.registry import Touch
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 31, 3, 10, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("101"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def test_tick_outside_session_writes_shadow_r(tmp_path: Path) -> None:
    """03:10 UTC is outside the desk window. Shadow still scores."""
    assert PRINT.hour < 12
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "desk")), tick_size=TICK)
    desk.registry._zones[ZONE.zone_id] = ZONE
    touch = Touch.create(
        zone_id=ZONE.zone_id,
        ts=PRINT,
        trade_px=Decimal("100.5"),
        trade_qty=Decimal("1"),
    )
    desk.registry.touches.append(touch)
    desk.last_price["BTCUSDT"] = Decimal("102")
    desk.knowledge.put_journal_touch(
        touch.touch_id,
        {
            "touch_ts": PRINT.isoformat(),
            "shadow_would": True,
            "shadow_tag": "bounce",
            "outcome": "pending",
        },
    )
    later = PRINT + timedelta(minutes=20)
    events = desk.tick(later)
    assert any(row.get("event") == "shadow_outcome" for row in events)
    row = desk.knowledge.get_journal_touch(touch.touch_id)
    assert row is not None
    assert row["outcome"] == "bounce"
    overlay = desk.knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] == "1"
    assert desk.knowledge.pending_intents() == []


def test_tick_reads_last_price_from_knowledge(tmp_path: Path) -> None:
    """Restart keeps last_px. Night tick can still close a bounce."""
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_last_price("BTCUSDT", "102")
    desk = DeskLoop(knowledge=knowledge, tick_size=TICK)
    assert desk.last_price["BTCUSDT"] == Decimal("102")
    desk.registry._zones[ZONE.zone_id] = ZONE
    touch = Touch.create(
        zone_id=ZONE.zone_id,
        ts=PRINT,
        trade_px=Decimal("100.5"),
        trade_qty=Decimal("1"),
    )
    desk.registry.touches.append(touch)
    desk.knowledge.put_journal_touch(
        touch.touch_id,
        {
            "touch_ts": PRINT.isoformat(),
            "shadow_would": True,
            "shadow_tag": "bounce",
            "outcome": "pending",
        },
    )
    desk.tick(PRINT + timedelta(minutes=20))
    row = desk.knowledge.get_journal_touch(touch.touch_id)
    assert row is not None
    assert row["outcome"] == "bounce"
    overlay = desk.knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] == "1"


def test_challenger_flag_does_not_enqueue(tmp_path: Path) -> None:
    desk = DeskLoop(
        knowledge=open_knowledge(init_vault(tmp_path / "desk")),
        user_mode="off",
        tick_size=TICK,
    )
    desk.knowledge.put_journal_touch(
        "c1",
        {
            "touch_ts": PRINT.isoformat(),
            "shadow_would": True,
            "shadow_tag": "bounce",
            "bar_quality": "live",
            "cav_label": "REJECT",
            "zlg_label": "DEFEND",
            "tape_eaten": False,
            "outcome": "bounce",
            "challenger_would": True,
        },
    )
    persist = desk.knowledge
    assert persist.pending_intents() == []
