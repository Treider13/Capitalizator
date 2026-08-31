"""F1: TAKER_OK is false. Proposed bounce is a limit idea."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.exec.strategy_bounce import (
    ORDER_TYPE,
    TAKER_OK,
    BounceSnapshot,
    BounceStrategy,
)
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.zones.model import Zone


def test_taker_flag_is_off() -> None:
    assert TAKER_OK is False
    assert ORDER_TYPE == "limit"


def test_propose_is_limit_bounce() -> None:
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )
    got = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
    ).propose(
        BounceSnapshot(
            now=datetime(2026, 8, 31, 14, 10, tzinfo=UTC),
            symbol="BTCUSDT",
            price=Decimal("100.5"),
            tick=Decimal("0.1"),
            trading_mode="demo",
            zone=zone,
            zones=(zone,),
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
        )
    )
    assert got is not None
    assert got.tag == "bounce"
    assert ORDER_TYPE == "limit"
