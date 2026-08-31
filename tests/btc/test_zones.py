"""2.9.1 — BTC map uses the same ZoneEngine as an alt. No second engine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.btc.regime import BtcRegime
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Bar

TICK = Decimal("0.1")


def _daily(symbol: str, day: datetime, high: str, low: str) -> Bar:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return Bar(
        symbol=symbol,
        tf="1d",
        open_ts=start,
        close_ts=start.replace(hour=23, minute=59, second=59),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high),
    )


def test_btc_has_support_resistance_and_regime() -> None:
    t = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
    bars = [
        _daily("BTCUSDT", datetime(2026, 8, 29, tzinfo=UTC), "100", "90"),
        _daily("BTCUSDT", datetime(2026, 8, 30, tzinfo=UTC), "120", "80"),
    ]
    zones = ZoneEngine(tick_size=TICK).build("BTCUSDT", t, bars)
    sides = {z.side for z in zones if z.method == "prior_day_hl"}
    assert sides == {"support", "resistance"}
    assert any(z.lo == Decimal("80") for z in zones)
    h4 = [
        Bar(
            symbol="BTCUSDT",
            tf="4h",
            open_ts=datetime(2026, 8, 30, hour, tzinfo=UTC),
            close_ts=datetime(2026, 8, 30, hour + 4, tzinfo=UTC),
            open=Decimal(close),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
        )
        for hour, high, low, close in (
            (0, "10", "8", "9"),
            (4, "11", "8", "10"),
            (8, "10.5", "8.5", "9.5"),
        )
    ]
    assert BtcRegime().classify(t, bars=h4) == "box"


def test_same_engine_class_builds_eth() -> None:
    engine = ZoneEngine(tick_size=TICK)
    t = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
    btc = [
        _daily("BTCUSDT", datetime(2026, 8, 29, tzinfo=UTC), "100", "90"),
        _daily("BTCUSDT", datetime(2026, 8, 30, tzinfo=UTC), "120", "80"),
    ]
    eth = [
        _daily("ETHUSDT", datetime(2026, 8, 29, tzinfo=UTC), "4", "3"),
        _daily("ETHUSDT", datetime(2026, 8, 30, tzinfo=UTC), "5", "2"),
    ]
    assert engine.build("BTCUSDT", t, btc)
    assert engine.build("ETHUSDT", t, eth)
    assert type(engine) is ZoneEngine


def test_regime_has_no_veto_method() -> None:
    from capitalizator.btc.regime import BtcRegime

    assert not hasattr(BtcRegime, "veto")
    assert not hasattr(BtcRegime(), "veto")
