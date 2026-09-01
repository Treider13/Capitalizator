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
    last_gap_segment,
    prior_same_tf,
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


def test_unclosed_bar_is_live_not_stagnant() -> None:
    """Close is not a fact until close_ts < t. Five equal prints are still LIVE."""
    hist = [_bar(i, close="100") for i in range(4)]
    current = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        close_ts=T,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert current.close_ts >= T
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_unclosed_zero_volume_is_live_not_illiquid() -> None:
    hist = [_bar(0, close="100", volume=Decimal("0"))]
    current = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        close_ts=T,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_exact_15pct_is_not_a_gap() -> None:
    a = _bar(0, close="100")
    b = _bar(1, close="115", open_="115")
    assert abs(b.open - a.close) / a.close == JUMP_RATIO_15M
    segs = split_on_gaps([a, b])
    assert len(segs) == 1
    assert len(segs[0]) == 2


def test_exact_15pct_into_current_keeps_segment() -> None:
    """Jump is strict >15%. Equality into the labeled bar must not empty ATR."""
    priors = [_bar(i, close="100", open_="100") for i in range(15)]
    current = _bar(17, close="115", open_="115")
    assert current.close_ts < T
    assert abs(current.open - priors[-1].close) / priors[-1].close == JUMP_RATIO_15M
    assert len(last_gap_segment(priors, current, t=T)) == 15


def test_mixed_symbol_or_tf_is_not_a_gap_series() -> None:
    btc = _bar(0, close="100")
    eth = _bar(1, close="116", open_="116", symbol="ETHUSDT")
    with pytest.raises(ValueError, match="one symbol"):
        split_on_gaps([btc, eth])
    other_tf = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=btc.open_ts,
        close_ts=btc.close_ts + timedelta(hours=1),
        open=Decimal("116"),
        high=Decimal("117"),
        low=Decimal("115"),
        close=Decimal("116"),
    )
    with pytest.raises(ValueError, match="one"):
        split_on_gaps([btc, other_tf])


def test_last_gap_segment_empty_when_current_jumps() -> None:
    priors = [_bar(i, close="130", open_="130") for i in range(15)]
    # i=17 closes 16:30, before T=16:45 — must stay a closed bar.
    jumped = _bar(17, close="100", open_="100")
    assert jumped.close_ts < T
    assert last_gap_segment(priors, jumped, t=T) == []
    cont = _bar(17, close="130", open_="130")
    assert len(last_gap_segment(priors, cont, t=T)) == 15


def test_wrong_tf_zero_volume_is_not_illiquid() -> None:
    """One 1h zero-vol bar closed before current would be illiquid if tf filter dropped."""
    ts = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    hist = [
        Bar(
            symbol="BTCUSDT",
            tf="1h",
            open_ts=ts,
            close_ts=ts + timedelta(hours=1),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("0"),
        )
    ]
    current = _bar(10, close="101", volume=Decimal("0"))
    assert hist[0].close_ts < current.close_ts
    assert prior_same_tf(hist, current, t=T) == []
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_other_symbol_zero_volume_is_not_illiquid() -> None:
    hist = [_bar(0, close="100", symbol="ETHUSDT", volume=Decimal("0"))]
    current = _bar(1, close="101", volume=Decimal("0"))
    assert prior_same_tf(hist, current, t=T) == []
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_later_zero_volume_is_not_illiquid() -> None:
    hist = [_bar(6, close="100", volume=Decimal("0"))]
    current = _bar(4, close="101", volume=Decimal("0"))
    assert hist[0].close_ts > current.close_ts
    assert hist[0].close_ts < T
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_unclosed_prior_does_not_make_illiquid() -> None:
    """Forming zero-vol bar is not a fact. Alone with a closed zero-vol current → LIVE."""
    hist = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=T - timedelta(minutes=15),
            close_ts=T,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("0"),
        )
    ]
    current = _bar(4, close="101", volume=Decimal("0"))
    assert hist[0].close_ts >= T
    assert current.close_ts < T
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_unclosed_prior_does_not_make_stagnant() -> None:
    """A forming bar in history is not a close fact. 3 closed + unclosed + current = 4."""
    hist = [_bar(i, close="100") for i in range(3)]
    hist.append(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=T - timedelta(minutes=15),
            close_ts=T,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
        )
    )
    current = _bar(4, close="100")
    assert hist[-1].close_ts >= T
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_wrong_tf_is_not_a_stagnant_prior() -> None:
    """4 same-symbol 1h closes before the 15m bar would be stagnant if tf filter dropped.

    A same-day 12:00+hours fixture leaves only two hourly closes before _bar(10)=14:45.
    """
    hist = []
    for i in range(4):
        ts = datetime(2026, 8, 29, 0, 0, tzinfo=UTC) + timedelta(hours=i)
        hist.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ts,
                close_ts=ts + timedelta(hours=1),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            )
        )
    current = _bar(10, close="100")
    assert sum(1 for b in hist if b.close_ts < current.close_ts) == 4
    assert prior_same_tf(hist, current, t=T) == []
    assert classify_bar_quality(hist, current, t=T) == LIVE
