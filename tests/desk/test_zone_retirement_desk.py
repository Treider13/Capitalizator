"""The desk retires stale zones once a minute: memory, persisted `zone` table and the
per-symbol zone cache all forget them, and the event is visible."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
T0 = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _trade(px: str, ts: datetime) -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                       recv_ts=ts, payload={"px": px, "qty": "1", "side": "buy"})


def test_desk_drops_retired_zone_everywhere(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off",
                    tick_size=Decimal("0.1"))
    stale = Zone.create(symbol="BTCUSDT", tf="15m", side="support", lo=Decimal("100"),
                        hi=Decimal("100.2"), method="swing", created_as_of=CREATED)
    desk.on_trade(_trade("150", T0), [stale])
    desk.persist_zones([stale])
    assert any(r["zone_id"] == stale.zone_id for r in desk.knowledge.list_zones())
    desk.tick(T0)
    assert stale.zone_id in desk.registry._zones
    at = T0 + timedelta(hours=desk.config.die_no_touch_h, seconds=1)
    out = desk.tick(at)
    retired = [e for e in out if e.get("event") == "zone_retired"]
    assert [e["zone_id"] for e in retired] == [stale.zone_id]
    assert stale.zone_id not in desk.registry._zones
    assert all(r["zone_id"] != stale.zone_id for r in desk.knowledge.list_zones())
    # a retired zone is still resolvable for the touches that reference it
    assert desk.registry.zone(stale.zone_id) == stale


def test_retirement_runs_at_most_once_a_minute(tmp_path: Path) -> None:
    desk = DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off",
                    tick_size=Decimal("0.1"))
    calls: list[datetime] = []
    original = desk.registry.retire_zones

    def spy(*, now: datetime):  # noqa: ANN202
        calls.append(now)
        return original(now=now)

    desk.registry.retire_zones = spy  # type: ignore[method-assign]
    desk.tick(T0)
    desk.tick(T0 + timedelta(seconds=30))
    desk.tick(T0 + timedelta(seconds=61))
    assert len(calls) == 2
