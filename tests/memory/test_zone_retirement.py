"""PHASE-BUILD `die_no_touch_h`: a zone the market has not traded for 24h is retired.

The key sat in registry.yaml and was read by nothing. Zones accumulated in
`Registry._zones` forever, and stale ones kept voting in `in_mid_range` /
`opposing_target`. Now: a zone stays while the engine keeps producing it or the
market keeps touching it; otherwise it dies after `die_no_touch_h`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.memory.registry import Registry
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)


def _zone(lo: str, hi: str, *, side: str = "support", created: datetime = CREATED) -> Zone:
    return Zone.create(symbol="BTCUSDT", tf="15m", side=side, lo=Decimal(lo), hi=Decimal(hi),
                       method="swing", created_as_of=created)


def _trade(px: str, *, ts: datetime) -> MarketEvent:
    return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                       recv_ts=ts, seq=None, payload={"px": px, "qty": "1", "side": "buy"})


def test_zone_without_touch_or_engine_refresh_dies_after_die_no_touch_h() -> None:
    reg = Registry(tick_size=TICK)
    stale = _zone("100", "100.2")
    live = _zone("200", "200.2")
    # both zones seen at PRINT (engine output on a print far from either)
    reg.on_trade(_trade("150", ts=PRINT), [stale, live])
    assert set(reg._zones) == {stale.zone_id, live.zone_id}
    # 23h later the engine still produces `live`, not `stale`
    later = PRINT + timedelta(hours=23)
    reg.on_trade(_trade("150", ts=later), [live])
    assert reg.retire_zones(now=later) == []
    # crossing 24h since `stale` was last seen: it dies, `live` stays
    at = PRINT + timedelta(hours=reg.config.die_no_touch_h, seconds=1)
    reg.on_trade(_trade("150", ts=at), [live])
    gone = reg.retire_zones(now=at)
    assert [z.zone_id for z in gone] == [stale.zone_id]
    assert set(reg._zones) == {live.zone_id}


def test_a_touch_keeps_the_zone_alive() -> None:
    reg = Registry(tick_size=TICK)
    zone = _zone("100", "100.2")
    reg.on_trade(_trade("100.1", ts=PRINT), [zone])  # touch
    reg.resolve(now=PRINT + timedelta(minutes=20), bars=[], last_px=Decimal("101"))  # bounce
    # 23h after the touch, engine no longer emits the zone
    reg.on_trade(_trade("150", ts=PRINT + timedelta(hours=23)), [])
    assert reg.retire_zones(now=PRINT + timedelta(hours=23)) == []
    # 24h after the LAST TOUCH it dies
    at = PRINT + timedelta(hours=reg.config.die_no_touch_h, seconds=1)
    assert [z.zone_id for z in reg.retire_zones(now=at)] == [zone.zone_id]


def test_retirement_kills_a_pending_touch_on_that_zone() -> None:
    reg = Registry(tick_size=TICK)
    zone = _zone("100", "100.2")
    reg.on_trade(_trade("100.1", ts=PRINT), [zone])
    # nothing resolves it (no bars, price sits still); pending outlives 6h only through
    # the timeout — here we force retirement first to prove the touch cannot dangle
    at = PRINT + timedelta(hours=reg.config.die_no_touch_h, seconds=1)
    reg.retire_zones(now=at)
    assert zone.zone_id not in reg._zones
    assert all(t.outcome != "pending" for t in reg.touches)
    assert reg.touches[0].outcome == "die"


def test_resolved_touches_on_retired_zones_keep_their_labels_for_counts() -> None:
    reg = Registry(tick_size=TICK)
    zone = _zone("100", "100.2")
    reg.on_trade(_trade("100.1", ts=PRINT), [zone])
    reg.fill_cav(cav_label="REJECT", touch_id=reg.touches[0].touch_id)
    reg.resolve(now=PRINT + timedelta(minutes=20), bars=[], last_px=Decimal("101"))
    n_before = reg.count_label("cav", "REJECT", "BTCUSDT")
    at = PRINT + timedelta(hours=reg.config.die_no_touch_h, seconds=1)
    reg.retire_zones(now=at)
    assert reg.count_label("cav", "REJECT", "BTCUSDT") == n_before == 1
