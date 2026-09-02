"""resolve_symbol does not apply ETH last_px to a BTC pending touch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.memory.registry import Registry, Touch
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Zone

CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def _zone(symbol: str, lo: str, hi: str) -> Zone:
    return Zone.create(
        symbol=symbol,
        tf="15m",
        side="support",
        lo=Decimal(lo),
        hi=Decimal(hi),
        method="prior_day_hl",
        created_as_of=CREATED,
    )


def _trade(symbol: str, px: str) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=PRINT,
        recv_ts=PRINT,
        payload={"px": px, "qty": "1", "side": "buy"},
    )


def test_missing_zone_stays_pending() -> None:
    btc = _zone("BTCUSDT", "100", "101")
    reg = Registry(tick_size=Decimal("0.1"))
    ghost = Touch.create(
        zone_id="ghost",
        ts=PRINT,
        trade_px=Decimal("100.5"),
        trade_qty=Decimal("1"),
    )
    reg.touches.append(ghost)
    assert reg.on_trade(_trade("BTCUSDT", "100.5"), [btc])
    later = PRINT + timedelta(minutes=20)
    changed = reg.resolve_symbol(
        "BTCUSDT",
        now=later,
        bars=[],
        last_px=Decimal("102"),
    )
    assert [t.outcome for t in changed] == ["bounce"]
    assert next(t for t in reg.touches if t.touch_id == ghost.touch_id).outcome == "pending"


def test_eth_price_does_not_bounce_btc() -> None:
    btc = _zone("BTCUSDT", "100", "101")
    eth = _zone("ETHUSDT", "2000", "2010")
    reg = Registry(tick_size=Decimal("0.1"))
    assert reg.on_trade(_trade("BTCUSDT", "100.5"), [btc, eth])
    later = PRINT + timedelta(minutes=20)
    changed = reg.resolve_symbol(
        "ETHUSDT",
        now=later,
        bars=[],
        last_px=Decimal("10000"),
    )
    assert changed == []
    assert reg.touches[0].outcome == "pending"
    bounced = reg.resolve_symbol(
        "BTCUSDT",
        now=later,
        bars=[],
        last_px=Decimal("102"),
    )
    assert [t.outcome for t in bounced] == ["bounce"]
