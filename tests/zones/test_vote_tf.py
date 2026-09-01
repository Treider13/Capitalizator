"""Map zones vote on working_tf. CAV is the 15m close, not the source horizon."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.patterns.cav import label
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Bar


TICK = Decimal("0.1")
T_BUILD = datetime(2026, 8, 31, 16, 30, tzinfo=UTC)
MAP_METHODS = frozenset({"prior_day_hl", "prior_session_hl", "vp_hyp"})


def _day_bar() -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 14, 15, tzinfo=UTC),
        open=Decimal("95"),
        high=Decimal("100"),
        low=Decimal("90"),
        close=Decimal("98"),
        volume=Decimal("10"),
    )


def test_engine_map_zones_use_working_tf() -> None:
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", T_BUILD, [_day_bar()], poc=Decimal("96"))
    mapped = [z for z in zones if z.method in MAP_METHODS]
    assert mapped
    assert {z.method for z in mapped} >= {"prior_day_hl", "prior_session_hl", "vp_hyp"}
    assert {z.tf for z in mapped} == {engine.config.working_tf}


def test_engine_prior_day_15m_close_can_reject() -> None:
    """Same geometry as acceptance fixtures: wick in, close inside support."""
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", T_BUILD, [_day_bar()])
    support = next(z for z in zones if z.method == "prior_day_hl" and z.side == "support")
    assert support.tf == "15m"
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 31, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 31, 16, 30, tzinfo=UTC),
        open=Decimal("90.1"),
        high=Decimal("90.5"),
        low=Decimal("89.9"),
        close=Decimal("90.1"),
    )
    t = datetime(2026, 8, 31, 16, 30, 1, tzinfo=UTC)
    assert label(support, bar, t=t, htf_bias="box") == "REJECT"


def test_foreign_tf_bar_on_map_zone_is_still_noise() -> None:
    """bar.tf == zone.tf stays. A 1h close is not the 15m vote."""
    engine = ZoneEngine(tick_size=TICK)
    zones = engine.build("BTCUSDT", T_BUILD, [_day_bar()])
    support = next(z for z in zones if z.method == "prior_day_hl" and z.side == "support")
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 31, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 31, 16, 30, tzinfo=UTC),
        open=Decimal("90.1"),
        high=Decimal("90.5"),
        low=Decimal("89.9"),
        close=Decimal("90.1"),
    )
    t = datetime(2026, 8, 31, 16, 30, 1, tzinfo=UTC)
    assert label(support, hourly, t=t, htf_bias="box") == "NOISE"


def test_two_builds_keep_same_map_ids() -> None:
    engine = ZoneEngine(tick_size=TICK)
    bars = [_day_bar()]
    a = engine.build("BTCUSDT", T_BUILD, bars, poc=Decimal("96"))
    b = engine.build("BTCUSDT", T_BUILD, bars, poc=Decimal("96"))
    assert [z.zone_id for z in a] == [z.zone_id for z in b]
