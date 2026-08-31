"""Dead K-line labels. Gap splits a segment. volume=None is not illiquid."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.patterns.bar_quality import (
    ILLIQUID,
    JUMP_RATIO_15M,
    LIVE,
    STAGNANT,
    atr,
    classify_bar_quality,
    split_on_gaps,
)
from capitalizator.zones.model import Bar

T = datetime(2026, 8, 30, 16, 45, tzinfo=UTC)


def _bar(
    i: int,
    *,
    close: str = "100",
    open_: str | None = None,
    volume: Decimal | None = None,
    symbol: str = "BTCUSDT",
) -> Bar:
    ts = datetime(2026, 8, 30, 12, 0, tzinfo=UTC) + timedelta(minutes=15 * i)
    px = Decimal(close)
    op = Decimal(open_) if open_ is not None else px
    return Bar(
        symbol=symbol,
        tf="15m",
        open_ts=ts,
        close_ts=ts + timedelta(minutes=15),
        open=op,
        high=max(op, px) + Decimal("1"),
        low=min(op, px) - Decimal("1"),
        close=px,
        volume=volume,
    )


def test_five_same_closes_are_stagnant() -> None:
    hist = [_bar(i, close="100") for i in range(4)]
    current = _bar(4, close="100")
    assert classify_bar_quality(hist, current, t=T) == STAGNANT
    assert classify_bar_quality(hist, current, t=T) == classify_bar_quality(hist, current, t=T)


def test_four_same_closes_are_live() -> None:
    hist = [_bar(i, close="100") for i in range(3)]
    current = _bar(3, close="100")
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_two_zero_volume_bars_are_illiquid() -> None:
    hist = [_bar(0, close="100", volume=Decimal("0"))]
    current = _bar(1, close="101", volume=Decimal("0"))
    assert classify_bar_quality(hist, current, t=T) == ILLIQUID


def test_volume_none_skips_illiquid() -> None:
    hist = [_bar(0, close="100", volume=None)]
    current = _bar(1, close="101", volume=None)
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_one_zero_volume_bar_is_live() -> None:
    current = _bar(0, close="101", volume=Decimal("0"))
    assert classify_bar_quality([], current, t=T) == LIVE


def test_stagnant_wins_over_illiquid() -> None:
    hist = [_bar(i, close="100", volume=Decimal("0")) for i in range(4)]
    current = _bar(4, close="100", volume=Decimal("0"))
    assert classify_bar_quality(hist, current, t=T) == STAGNANT


def test_other_symbol_is_not_prior() -> None:
    hist = [_bar(i, close="100", symbol="ETHUSDT") for i in range(4)]
    current = _bar(4, close="100")
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_later_bar_is_not_a_prior() -> None:
    hist = [_bar(i, close="100") for i in range(3)] + [_bar(6, close="100")]
    current = _bar(4, close="100")
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_split_on_gaps_breaks_after_15pct() -> None:
    a = _bar(0, close="100")
    b = _bar(1, close="116", open_="116")
    segs = split_on_gaps([a, b])
    assert abs(b.open - a.close) / a.close > JUMP_RATIO_15M
    assert len(segs) == 2
    assert [len(s) for s in segs] == [1, 1]


def test_split_on_gaps_keeps_14pct() -> None:
    a = _bar(0, close="100")
    b = _bar(1, close="114", open_="114")
    segs = split_on_gaps([a, b])
    assert abs(b.open - a.close) / a.close < JUMP_RATIO_15M
    assert len(segs) == 1
    assert len(segs[0]) == 2


def test_atr_needs_fifteen_bars() -> None:
    bars = [_bar(i) for i in range(14)]
    assert atr(bars) is None
    bars.append(_bar(14))
    assert atr(bars) == Decimal("2")


def test_negative_volume_rejected() -> None:
    with pytest.raises(ValueError, match="volume"):
        _bar(0, volume=Decimal("-1"))
