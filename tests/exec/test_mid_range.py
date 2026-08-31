"""1.6.2 — price exactly between support and resistance → 0 intents."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy, in_mid_range
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.zones.model import Zone

SESSION = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def _zone(*, side: str, lo: str, hi: str) -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side=side,  # type: ignore[arg-type]
        lo=Decimal(lo),
        hi=Decimal(hi),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )


def test_exact_mid_is_mid_range() -> None:
    support = _zone(side="support", lo="100", hi="101")
    resist = _zone(side="resistance", lo="109", hi="110")
    mid = (Decimal("101") + Decimal("109")) / 2
    assert mid == Decimal("105")
    assert in_mid_range(mid, (support, resist)) is True
    assert in_mid_range(Decimal("100.5"), (support, resist)) is False


def test_exact_mid_yields_no_intent() -> None:
    support = _zone(side="support", lo="100", hi="101")
    resist = _zone(side="resistance", lo="109", hi="110")
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
    )
    snap = BounceSnapshot(
        now=SESSION,
        symbol="BTCUSDT",
        price=Decimal("105"),
        tick=Decimal("0.1"),
        trading_mode="demo",
        zone=support,
        zones=(support, resist),
        spread_frac=Decimal("0.001"),
        typical_move=Decimal("0.01"),
    )
    assert strat.propose(snap) is None
