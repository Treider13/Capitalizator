"""0.3.1 — a zone that needs bar t+1 does not exist in a run only up to t."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Bar

TICK = Decimal("0.1")


def _daily(day: datetime, high: str, low: str) -> Bar:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return Bar(
        symbol="BTCUSDT",
        tf="1d",
        open_ts=start,
        close_ts=start.replace(hour=23, minute=59, second=59),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high),
    )


def _m15(*, hour: int, minute: int, high: str, low: str, close: str) -> Bar:
    open_ts = datetime(2026, 8, 30, hour, minute, tzinfo=UTC)
    close_minute = minute + 15
    close_ts = (
        open_ts.replace(minute=close_minute)
        if close_minute < 60
        else open_ts.replace(hour=hour + 1, minute=close_minute - 60)
    )
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=open_ts,
        close_ts=close_ts,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_prior_day_zone_from_tomorrow_does_not_exist_today() -> None:
    bars = [
        _daily(datetime(2026, 8, 29, tzinfo=UTC), "100", "90"),
        _daily(datetime(2026, 8, 30, tzinfo=UTC), "120", "80"),
    ]
    engine = ZoneEngine(tick_size=TICK)
    during_30 = engine.build("BTCUSDT", datetime(2026, 8, 30, 12, 0, tzinfo=UTC), bars)
    after_30 = engine.build("BTCUSDT", datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC), bars)
    early_ids = {z.zone_id for z in during_30}
    late_ids = {z.zone_id for z in after_30}
    assert early_ids
    # Aug 30 H/L (80 / 120) only becomes "yesterday" on Aug 31.
    assert not any(z.lo == Decimal("80") for z in during_30)
    assert any(z.lo == Decimal("80") and z.method == "prior_day_hl" for z in after_30)
    assert late_ids - early_ids
    for z in after_30:
        if z.lo == Decimal("80"):
            assert z.zone_id not in early_ids


def test_swing_needs_confirmation_bar() -> None:
    bars = [
        _m15(hour=13, minute=0, high="10", low="9", close="9.5"),
        _m15(hour=13, minute=15, high="20", low="10", close="19"),
        _m15(hour=13, minute=30, high="11", low="10", close="10.5"),
    ]
    engine = ZoneEngine(tick_size=TICK)
    before = engine.build("BTCUSDT", bars[2].close_ts, bars)
    after = engine.build(
        "BTCUSDT", datetime(2026, 8, 30, 13, 45, 1, tzinfo=UTC), bars
    )
    assert not any(z.method == "swing" for z in before)
    swings = [z for z in after if z.method == "swing" and z.side == "resistance"]
    assert len(swings) == 1
    assert swings[0].hi == Decimal("20")
