"""Fourth session intent is reject. Does not chase frequency."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.budget import SessionBudget
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.zones.model import Zone


def _zone() -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("101"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )


def test_fourth_bounce_is_rejected() -> None:
    zone = _zone()
    snap = BounceSnapshot(
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
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        budget=SessionBudget(),
        require_card=False,
    )
    assert strat.propose(snap) is not None
    assert strat.propose(snap) is not None
    assert strat.propose(snap) is not None
    assert strat.propose(snap) is None
    assert strat.budget.n == 3
