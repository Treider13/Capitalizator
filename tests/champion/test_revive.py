"""Pending journal + stored zone come back after a new DeskLoop."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.memory.revive import load_pending, touch_from_journal, zone_from_payload
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.zones.model import Zone

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


def _zone_row() -> dict[str, str]:
    return {
        "zone_id": ZONE.zone_id,
        "symbol": ZONE.symbol,
        "tf": ZONE.tf,
        "side": ZONE.side,
        "lo": str(ZONE.lo),
        "hi": str(ZONE.hi),
        "method": ZONE.method,
        "created_as_of": ZONE.created_as_of.isoformat(),
    }


def test_missing_zone_is_not_revived() -> None:
    assert (
        touch_from_journal(
            {
                "touch_id": "t1",
                "zone_id": "ghost",
                "touch_ts": PRINT.isoformat(),
                "trade_px": "100.5",
                "trade_qty": "1",
                "outcome": "pending",
            }
        )
        is not None
    )
    assert zone_from_payload({"zone_id": "ghost", "symbol": "BTCUSDT"}) is None


def test_resolved_row_is_not_revived() -> None:
    assert (
        touch_from_journal(
            {
                "touch_id": "t1",
                "zone_id": ZONE.zone_id,
                "touch_ts": PRINT.isoformat(),
                "trade_px": "100.5",
                "trade_qty": "1",
                "outcome": "bounce",
            }
        )
        is None
    )


def test_load_pending_needs_stored_zone(tmp_path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_journal_touch(
        "t1",
        {
            "touch_id": "t1",
            "zone_id": ZONE.zone_id,
            "touch_ts": PRINT.isoformat(),
            "trade_px": "100.5",
            "trade_qty": "1",
            "outcome": "pending",
        },
    )
    zones, touches = load_pending(knowledge)
    assert zones == []
    assert touches == []
    knowledge.put_zone(ZONE.zone_id, _zone_row())
    zones, touches = load_pending(knowledge)
    assert [z.zone_id for z in zones] == [ZONE.zone_id]
    assert [t.touch_id for t in touches] == ["t1"]
    assert touches[0].outcome == "pending"
