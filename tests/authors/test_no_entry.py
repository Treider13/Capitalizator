"""2.12.4 — author never accept. No zone → reject."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.authors.score import author_accepts
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine

SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def test_author_never_accepts() -> None:
    assert author_accepts(has_zone=False) is False
    assert author_accepts(has_zone=True) is False


def test_propose_without_zone_is_none_even_in_demo() -> None:
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
    )
    snap = BounceSnapshot(
        now=SESSION,
        symbol="BTCUSDT",
        price=Decimal("100.5"),
        tick=Decimal("0.1"),
        trading_mode="demo",
        zone=None,
        zones=(),
        spread_frac=Decimal("0.001"),
        typical_move=Decimal("0.01"),
    )
    assert strat.propose(snap) is None
