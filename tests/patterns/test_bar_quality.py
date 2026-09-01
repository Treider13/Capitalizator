"""Dead K-line labels. Gap splits a segment. volume=None is not illiquid."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
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


def test_naive_t_is_rejected() -> None:
    current = _bar(0)
    naive = datetime(2026, 8, 30, 16, 45)
    with pytest.raises(TypeError, match="naive"):
        classify_bar_quality([], current, t=naive)
    with pytest.raises(TypeError, match="naive"):
        last_gap_segment([], current, t=naive)


def test_zero_close_is_a_gap() -> None:
    """prev.close=0 cannot divide. Treat as a segment break, do not crash."""
    a = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 15, tzinfo=UTC),
        open=Decimal("0"),
        high=Decimal("1"),
        low=Decimal("0"),
        close=Decimal("0"),
    )
    b = _bar(1, close="100", open_="100")
    segs = split_on_gaps([a, b])
    assert len(segs) == 2
    assert last_gap_segment([a], b, t=T) == []


def test_five_same_closes_are_stagnant() -> None:
    hist = [_bar(i, close="100") for i in range(4)]
    current = _bar(4, close="100")
    assert classify_bar_quality(hist, current, t=T) == STAGNANT
    assert classify_bar_quality(hist, current, t=T) == classify_bar_quality(hist, current, t=T)


def test_four_same_closes_are_live() -> None:
    hist = [_bar(i, close="100") for i in range(3)]
    current = _bar(3, close="100")
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_stagnant_is_the_last_five_closes() -> None:
    """Five equal closes in the series is not enough if the last five are broken."""
    hist = [_bar(i, close="100") for i in range(4)] + [_bar(4, close="101")]
    current = _bar(5, close="100")
    assert sum(1 for b in hist + [current] if b.close == Decimal("100")) == 5
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_stagnant_sorts_before_the_last_five() -> None:
    """Late 101 first in the list: last-five without a sort are five 100s."""
    late = _bar(4, close="101")
    early = [_bar(i, close="100") for i in range(4)]
    current = _bar(5, close="100")
    hist = [late] + early
    assert hist[0].close == Decimal("101")
    assert all(b.close == Decimal("100") for b in hist[1:])
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


def test_illiquid_is_the_last_two_zero_volumes() -> None:
    """A zero-vol bar earlier in the series is not the neighbor. Two zeros anywhere would fake ILLIQUID."""
    hist = [_bar(0, close="100", volume=Decimal("0")), _bar(1, close="101", volume=Decimal("1"))]
    current = _bar(2, close="102", volume=Decimal("0"))
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_illiquid_sorts_before_the_last_two() -> None:
    """Early zero last in the list: last-two without a sort are two zeros."""
    early_zero = _bar(0, close="100", volume=Decimal("0"))
    later_vol = _bar(1, close="101", volume=Decimal("1"))
    current = _bar(2, close="102", volume=Decimal("0"))
    hist = [later_vol, early_zero]
    assert hist[-1].volume == Decimal("0")
    assert classify_bar_quality(hist, current, t=T) == LIVE


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


def test_split_on_gaps_sorts_before_the_cut() -> None:
    """List [116, 100]: down 16/116 < 15%, one segment if unsorted. Time order is a 16% up gap."""
    early = _bar(0, close="100")
    late = _bar(1, close="116", open_="116")
    assert abs(late.open - early.close) / early.close > JUMP_RATIO_15M
    assert abs(early.open - late.close) / late.close < JUMP_RATIO_15M
    segs = split_on_gaps([late, early])
    assert [len(s) for s in segs] == [1, 1]
    assert segs[0] == [early]
    assert segs[1] == [late]


def test_atr_n_must_be_positive() -> None:
    with pytest.raises(ValueError, match="atr n"):
        atr([_bar(0)], n=0)


def test_jump_ratio_must_be_positive() -> None:
    with pytest.raises(ValueError, match="jump_ratio"):
        split_on_gaps([_bar(0), _bar(1)], jump_ratio=Decimal("0"))


def test_atr_needs_fifteen_bars() -> None:
    bars = [_bar(i) for i in range(14)]
    assert atr(bars) is None
    bars.append(_bar(14))
    assert atr(bars) == Decimal("2")


def test_atr_uses_the_last_window() -> None:
    """Identical-TR series does not lock last-vs-first. Five wide bars at the start must not enter ATR."""
    wide = []
    tight = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(5):
        ts = start + timedelta(minutes=15 * i)
        wide.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("100"),
                close=Decimal("100"),
            )
        )
    for i in range(5, 20):
        ts = start + timedelta(minutes=15 * i)
        tight.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("100"),
            )
        )
    series = wide + tight
    assert len(series) == 20
    assert atr(series[:15]) == Decimal("60") / Decimal("14")
    assert atr(series) == Decimal("2")


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


def test_offset_t_keeps_a_later_utc_close_unclosed() -> None:
    """+3 16:45 is 13:45Z. A 16:30Z close is not a fact yet — LIVE, empty ATR segment."""
    plus3 = timezone(timedelta(hours=3))
    t = datetime(2026, 8, 30, 16, 45, tzinfo=plus3)
    hist = [_bar(i, close="100") for i in range(4)]
    current = _bar(17, close="100")
    assert current.close_ts.hour == 16
    assert current.close_ts.minute == 30
    assert t.hour == 16
    assert current.close_ts >= t.astimezone(UTC)
    assert classify_bar_quality(hist, current, t=t) == LIVE
    assert last_gap_segment(hist, current, t=t) == []


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


def test_early_gap_appended_last_is_not_the_segment_cut() -> None:
    """List order is not time. priors[-1] without a sort would empty the ATR window."""
    priors = [_bar(i, close="101", open_="101") for i in range(15)]
    early = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 11, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 11, 14, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    current = _bar(17, close="101", open_="101")
    mixed = priors + [early]
    assert mixed[-1].close == Decimal("80")
    assert abs(current.open - mixed[-1].close) / mixed[-1].close > JUMP_RATIO_15M
    assert len(last_gap_segment(mixed, current, t=T)) == 15
    assert last_gap_segment(mixed, current, t=T) == priors


def test_14pct_into_current_keeps_segment() -> None:
    priors = [_bar(i, close="100", open_="100") for i in range(15)]
    current = _bar(17, close="114", open_="114")
    assert abs(current.open - priors[-1].close) / priors[-1].close < JUMP_RATIO_15M
    assert len(last_gap_segment(priors, current, t=T)) == 15


def test_exact_15pct_into_current_keeps_segment() -> None:
    """Jump is strict >15%. Equality into the labeled bar must not empty ATR."""
    priors = [_bar(i, close="100", open_="100") for i in range(15)]
    current = _bar(17, close="115", open_="115")
    assert current.close_ts < T
    assert abs(current.open - priors[-1].close) / priors[-1].close == JUMP_RATIO_15M
    assert len(last_gap_segment(priors, current, t=T)) == 15


def test_down_jump_is_a_gap() -> None:
    """Gap is |open − prev.close|. Dropping abs() keeps a 16% down move in the old ATR window."""
    a = _bar(0, close="100", open_="100")
    b = _bar(1, close="84", open_="84")
    assert (b.open - a.close) / a.close < 0
    assert abs(b.open - a.close) / a.close > JUMP_RATIO_15M
    assert [len(s) for s in split_on_gaps([a, b])] == [1, 1]
    priors = [_bar(i, close="100", open_="100") for i in range(15)]
    current = _bar(17, close="84", open_="84")
    assert last_gap_segment(priors, current, t=T) == []


def test_exact_15pct_down_is_not_a_gap() -> None:
    priors = [_bar(i, close="100", open_="100") for i in range(15)]
    current = _bar(17, close="85", open_="85")
    assert (current.open - priors[-1].close) / priors[-1].close == Decimal("-0.15")
    assert abs(current.open - priors[-1].close) / priors[-1].close == JUMP_RATIO_15M
    assert [len(s) for s in split_on_gaps([priors[-1], current])] == [2]
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
