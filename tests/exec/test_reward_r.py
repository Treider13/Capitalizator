"""Bounce keeps 1.5/2R. Breakout and failed_break need a real 3R zone, not a invented multiple."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.exec.strategy_bounce import (
    BREAK_MIN_R,
    DEFAULT_R,
    MIN_R,
    default_multiple,
    opposing_target,
    reward_multiple,
    take_profit,
)
from capitalizator.zones.model import Zone


def _zone(*, lo: str, hi: str, side: str = "resistance", symbol: str = "BTCUSDT") -> Zone:
    return Zone.create(
        symbol=symbol,
        tf="15m",
        side=side,  # type: ignore[arg-type]
        lo=Decimal(lo),
        hi=Decimal(hi),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )


def test_bounce_multiples_unchanged() -> None:
    assert MIN_R == Decimal("1.5")
    assert DEFAULT_R == Decimal("2")
    assert reward_multiple("bounce") == MIN_R
    assert default_multiple("bounce") == DEFAULT_R


def test_break_ideas_use_three_r() -> None:
    assert BREAK_MIN_R == Decimal("3")
    assert reward_multiple("breakout") == BREAK_MIN_R
    assert reward_multiple("failed_break") == BREAK_MIN_R


def test_next_zone_below_three_r_rejects_breakout() -> None:
    nxt = _zone(lo="102", hi="103")
    assert (
        take_profit("buy", Decimal("100.5"), Decimal("99.2"), nxt, idea="breakout")
        is None
    )


def test_next_zone_below_three_r_still_ok_for_bounce_if_one_point_five() -> None:
    """1.5R from 100.5/99.2 is 1.95. Zone at 103.5 is enough for bounce, not 3R."""
    nxt = _zone(lo="103.5", hi="104")
    bounce = take_profit("buy", Decimal("100.5"), Decimal("99.2"), nxt, idea="bounce")
    brk = take_profit("buy", Decimal("100.5"), Decimal("99.2"), nxt, idea="breakout")
    assert bounce == Decimal("103.5")
    assert brk is None


def test_no_next_zone_breakout_has_no_target() -> None:
    assert take_profit("buy", Decimal("100.5"), Decimal("99.2"), None, idea="breakout") is None
    assert (
        take_profit("sell", Decimal("100.5"), Decimal("101.8"), None, idea="failed_break")
        is None
    )


def test_break_ideas_have_no_default_multiple() -> None:
    with pytest.raises(ValueError, match="no default"):
        default_multiple("breakout")
    with pytest.raises(ValueError, match="no default"):
        default_multiple("failed_break")


def test_opposing_target_is_nearest_same_symbol() -> None:
    near = _zone(lo="104", hi="105")
    far = _zone(lo="110", hi="111")
    other = _zone(lo="103", hi="103.5", symbol="ETHUSDT")
    got = opposing_target(
        (near, far, other),
        side="buy",
        entry=Decimal("100.5"),
        symbol="BTCUSDT",
    )
    assert got is near


def test_opposing_target_missing_is_none() -> None:
    only = _zone(lo="100", hi="101", side="support")
    assert (
        opposing_target((only,), side="buy", entry=Decimal("100.5"), symbol="BTCUSDT")
        is None
    )
