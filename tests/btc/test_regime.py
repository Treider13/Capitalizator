"""BTC regime is a label. No veto() in this step. Unknown is not invented."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.btc.regime import BtcRegime
from capitalizator.memory.registry import Registry
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

T = datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC)


def _h4(hour: int, high: str, low: str, close: str) -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="4h",
        open_ts=datetime(2026, 8, 30, hour, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, hour + 4, tzinfo=UTC),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_break_up_is_trend() -> None:
    bars = [
        _h4(0, "10", "8", "9"),
        _h4(4, "11", "8", "10"),
        _h4(8, "20", "12", "19"),
    ]
    assert BtcRegime().classify(T, bars=bars) == "trend"


def test_inside_range_is_box() -> None:
    bars = [
        _h4(0, "10", "8", "9"),
        _h4(4, "11", "8", "10"),
        _h4(8, "10.5", "8.5", "9.5"),
    ]
    assert BtcRegime().classify(T, bars=bars) == "box"


def test_known_news_is_news() -> None:
    assert (
        BtcRegime().classify(
            T,
            htf_bias="box",
            news_known_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        )
        == "news"
    )


def test_future_news_is_invisible() -> None:
    assert (
        BtcRegime().classify(
            T,
            htf_bias="box",
            news_known_at=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        )
        == "box"
    )


def test_unknown_is_none() -> None:
    assert BtcRegime().classify(T, bars=[]) is None


def test_no_veto_method() -> None:
    assert not hasattr(BtcRegime, "veto")
    assert not hasattr(BtcRegime(), "veto")


def test_registry_writes_regime() -> None:
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
    )
    print_ts = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    reg = Registry(tick_size=Decimal("0.1"))
    trade = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=print_ts,
        recv_ts=print_ts,
        seq=None,
        payload={"px": "100.1", "qty": "0.001", "side": "buy"},
    )
    opened = reg.on_trade(trade, [zone])
    assert opened[0].btc_regime is None
    reg.fill_btc(regime="box")
    assert reg.touches[0].btc_regime == "box"
