"""0.3.3 — poke a zone, leave, no close beyond → bounce. Two runs match."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.memory.registry import Registry
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _trade(px: str, *, ts: datetime = PRINT) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": px, "qty": "0.001", "side": "buy"},
    )


def _bar(close: str, *, close_ts: datetime) -> Bar:
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=close_ts - timedelta(minutes=15),
        close_ts=close_ts,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
    )


def test_poke_and_leave_without_close_beyond_is_bounce() -> None:
    reg = Registry(tick_size=TICK)
    opened = reg.on_trade(_trade("100.1"), [ZONE])
    assert len(opened) == 1
    assert opened[0].outcome == "pending"
    later = PRINT + timedelta(minutes=20)
    changed = reg.resolve(now=later, bars=[], last_px=Decimal("101.0"))
    assert [t.outcome for t in changed] == ["bounce"]
    assert reg.touches[0].outcome == "bounce"


def test_working_tf_close_beyond_is_break() -> None:
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=CREATED,
    )
    reg = Registry(tick_size=TICK)
    reg.on_trade(_trade("100.1"), [zone])
    close_ts = PRINT + timedelta(minutes=15)
    bar = _bar("99.9", close_ts=close_ts)
    later = close_ts + timedelta(seconds=1)
    changed = reg.resolve(now=later, bars=[bar], last_px=Decimal("101.0"))
    assert [t.outcome for t in changed] == ["break"]


def test_junior_tf_close_beyond_senior_zone_is_not_break() -> None:
    """A 1d level is not broken by a 15m close through the band."""
    reg = Registry(tick_size=TICK)
    reg.on_trade(_trade("100.1"), [ZONE])
    close_ts = PRINT + timedelta(minutes=15)
    bar = _bar("99.9", close_ts=close_ts)
    later = close_ts + timedelta(seconds=1)
    changed = reg.resolve(now=later, bars=[bar], last_px=Decimal("100.1"))
    assert changed == []
    assert reg.touches[0].outcome == "pending"


def test_own_tf_close_beyond_is_break() -> None:
    reg = Registry(tick_size=TICK)
    reg.on_trade(_trade("100.1"), [ZONE])
    close_ts = PRINT + timedelta(hours=8)
    daily = Bar(
        symbol="BTCUSDT",
        tf="1d",
        open_ts=close_ts - timedelta(days=1),
        close_ts=close_ts,
        open=Decimal("100.1"),
        high=Decimal("100.1"),
        low=Decimal("99.9"),
        close=Decimal("99.9"),
    )
    later = close_ts + timedelta(seconds=1)
    changed = reg.resolve(now=later, bars=[daily], last_px=Decimal("101.0"))
    assert [t.outcome for t in changed] == ["break"]


def test_pending_past_timeout_is_die() -> None:
    reg = Registry(tick_size=TICK)
    reg.on_trade(_trade("100.1"), [ZONE])
    later = PRINT + timedelta(hours=6, seconds=1)
    changed = reg.resolve(now=later, bars=[], last_px=Decimal("100.1"))
    assert [t.outcome for t in changed] == ["die"]


def test_zone_created_at_print_is_invisible() -> None:
    late = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=PRINT,
    )
    reg = Registry(tick_size=TICK)
    assert reg.on_trade(_trade("100.1"), [late]) == []


def test_second_print_while_pending_is_same_touch() -> None:
    reg = Registry(tick_size=TICK)
    first = reg.on_trade(_trade("100.1"), [ZONE])
    again = reg.on_trade(_trade("100.15", ts=PRINT + timedelta(seconds=1)), [ZONE])
    assert len(first) == 1
    assert again == []
    assert len(reg.touches) == 1


def test_other_symbol_same_price_is_not_a_touch() -> None:
    eth = Zone.create(
        symbol="ETHUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    reg = Registry(tick_size=TICK)
    assert reg.on_trade(_trade("100.1"), [eth]) == []


def test_two_replays_same_touch_ids() -> None:
    def run() -> list[str]:
        reg = Registry(tick_size=TICK)
        reg.on_trade(_trade("100.1"), [ZONE])
        later = PRINT + timedelta(minutes=20)
        reg.resolve(now=later, bars=[], last_px=Decimal("101.0"))
        return [f"{t.touch_id}:{t.outcome}" for t in reg.touches]

    assert run() == run()
    assert run()[0].endswith(":bounce")
