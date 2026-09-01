"""0.3.1 — two builds of the same bars at the same t → the same zone_id list."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.ids import make_zone_id
from capitalizator.zones.model import Bar, Zone


def test_two_builds_same_ids() -> None:
    bars = [
        Bar(
            symbol="BTCUSDT",
            tf="1d",
            open_ts=datetime(2026, 8, 29, tzinfo=UTC),
            close_ts=datetime(2026, 8, 29, 23, 59, 59, tzinfo=UTC),
            open=Decimal("95"),
            high=Decimal("100"),
            low=Decimal("90"),
            close=Decimal("98"),
        )
    ]
    engine = ZoneEngine(tick_size=Decimal("0.1"))
    t = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    a = engine.build("BTCUSDT", t, bars)
    b = engine.build("BTCUSDT", t, bars)
    assert [z.zone_id for z in a] == [z.zone_id for z in b]
    assert {z.method for z in a} >= {"prior_day_hl"}
    assert "vp_hyp" not in {z.method for z in a}
    assert {z.side for z in a} == {"support", "resistance"}
    assert len(a) >= 2
    with_poc = engine.build("BTCUSDT", t, bars, poc=Decimal("96"))
    assert {z.method for z in with_poc} >= {"prior_day_hl", "vp_hyp"}
    poc_zones = [z for z in with_poc if z.method == "vp_hyp"]
    assert any(z.lo == Decimal("96") for z in poc_zones)


def test_zone_id_is_blake2s_of_fields() -> None:
    created = datetime(2026, 8, 30, tzinfo=UTC)
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("90"),
        hi=Decimal("90.2"),
        method="prior_day_hl",
        created_as_of=created,
    )
    assert zone.zone_id == make_zone_id(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("90"),
        hi=Decimal("90.2"),
        method="prior_day_hl",
        created_as_of=created,
    )
    assert len(zone.zone_id) == 32


def test_non_positive_zone_price_rejected() -> None:
    with pytest.raises(ValueError, match="price"):
        Zone.create(
            symbol="BTCUSDT",
            tf="1d",
            side="support",
            lo=Decimal("0"),
            hi=Decimal("0.2"),
            method="prior_day_hl",
            created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
        )
