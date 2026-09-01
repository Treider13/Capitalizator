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


def test_same_close_ts_twin_is_not_a_stagnant_prior() -> None:
    """3 same + a twin of current would be 5 if `<= close_ts` or `is not current` leaked."""
    hist = [_bar(i, close="100") for i in range(3)]
    current = _bar(5, close="100")
    twin = _bar(5, close="100")
    assert twin.close_ts == current.close_ts
    assert twin is not current
    assert classify_bar_quality(hist + [twin], current, t=T) == LIVE


def test_same_close_ts_twin_is_not_an_illiquid_prior() -> None:
    """A twin zero-vol bar with the current close_ts is not the neighbor."""
    current = _bar(5, close="101", volume=Decimal("0"))
    twin = _bar(5, close="100", volume=Decimal("0"))
    assert twin.close_ts == current.close_ts
    assert twin is not current
    assert classify_bar_quality([], current, t=T) == LIVE
    assert classify_bar_quality([twin], current, t=T) == LIVE


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


def test_three_btc_and_one_eth_do_not_stagnate() -> None:
    """3 same BTC + 1 ETH + current is 5 prints. Counting every symbol would STAGNANT."""
    hist = [_bar(i, close="100") for i in range(3)] + [_bar(3, close="100", symbol="ETHUSDT")]
    current = _bar(4, close="100")
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(hist[:3], current, t=T) == LIVE
    assert classify_bar_quality([_bar(i, close="100") for i in range(4)], current, t=T) == STAGNANT


def test_stagnant_last_five_ignores_foreign_symbol_different_close() -> None:
    """4 same BTC + ETH 200 + current 100. Mixed last-5 is broken. Same-series last-5 is STAGNANT."""
    hist = [_bar(i, close="100") for i in range(4)] + [_bar(4, close="200", symbol="ETHUSDT")]
    current = _bar(5, close="100")
    assert classify_bar_quality(hist[:4], current, t=T) == STAGNANT
    assert classify_bar_quality(hist, current, t=T) == STAGNANT


def test_stagnant_last_five_ignores_foreign_tf_different_close() -> None:
    """4 same 15m + 1h 200 between them and current. Mixed last-5 is broken. Same-tf last-5 is STAGNANT."""
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 20, tzinfo=UTC),
        open=Decimal("200"),
        high=Decimal("201"),
        low=Decimal("199"),
        close=Decimal("200"),
    )
    hist = [_bar(i, close="100") for i in range(4)] + [hourly]
    current = _bar(5, close="100")
    assert hourly.close_ts < current.close_ts
    assert _bar(3, close="100").close_ts < hourly.close_ts
    assert classify_bar_quality(hist[:4], current, t=T) == STAGNANT
    assert classify_bar_quality(hist, current, t=T) == STAGNANT


def test_eth_stagnant_last_five_ignores_btc_different_close() -> None:
    """Hardcoded `history is BTC` drops four ETH 100s and keeps BTC 200 — last-5 breaks."""
    hist = [_bar(i, close="100", symbol="ETHUSDT") for i in range(4)] + [_bar(4, close="200")]
    current = _bar(5, close="100", symbol="ETHUSDT")
    assert classify_bar_quality(hist[:4], current, t=T) == STAGNANT
    assert classify_bar_quality(hist, current, t=T) == STAGNANT
    assert classify_bar_quality([hist[4]], current, t=T) == LIVE


def test_hourly_stagnant_last_five_ignores_15m_different_close() -> None:
    """Hardcoded `tf==15m` drops four 1h 100s and keeps a 15m 200 — last-5 breaks."""
    hourlies = []
    start = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    for i in range(4):
        ts = start + timedelta(hours=i)
        hourlies.append(
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
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 15, tzinfo=UTC),
        open=Decimal("200"),
        high=Decimal("201"),
        low=Decimal("199"),
        close=Decimal("200"),
    )
    current = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 12, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert hourlies[-1].close_ts < foreign.close_ts < current.close_ts
    assert current.close_ts < T
    assert classify_bar_quality(hourlies, current, t=T) == STAGNANT
    assert classify_bar_quality(hourlies + [foreign], current, t=T) == STAGNANT


def test_three_15m_and_one_1h_do_not_stagnate() -> None:
    """3 same 15m + 1h + current is 5 prints. Counting every tf would STAGNANT."""
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 11, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    hist = [_bar(i, close="100") for i in range(3)] + [hourly]
    current = _bar(4, close="100")
    assert hourly.close_ts < current.close_ts
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality([_bar(i, close="100") for i in range(4)], current, t=T) == STAGNANT


def test_btc_history_does_not_stagnate_an_eth_bar() -> None:
    """Hardcoded `history is BTC` would STAGNANT an ETH print. Filter is current.symbol."""
    hist = [_bar(i, close="100") for i in range(4)]
    current = _bar(4, close="100", symbol="ETHUSDT")
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(hist, _bar(4, close="100"), t=T) == STAGNANT


def test_15m_history_does_not_stagnate_a_1h_bar() -> None:
    """Hardcoded `tf==15m` would STAGNANT a 1h print. Filter is current.tf."""
    hist = [_bar(i, close="100") for i in range(4)]
    current = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert current.close_ts < T
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(hist, _bar(4, close="100"), t=T) == STAGNANT


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


def test_split_on_gaps_tiebreaks_equal_close_ts_by_open() -> None:
    """Same close_ts: sort-by-close only is stable and keeps list [116, 100] — down 16/116 < 15%."""
    close = datetime(2026, 8, 30, 12, 15, tzinfo=UTC)
    early = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    late = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=close,
        open=Decimal("116"),
        high=Decimal("117"),
        low=Decimal("115"),
        close=Decimal("116"),
    )
    assert early.close_ts == late.close_ts
    assert abs(late.open - early.close) / early.close > JUMP_RATIO_15M
    assert abs(early.open - late.close) / late.close < JUMP_RATIO_15M
    segs = split_on_gaps([late, early])
    assert [len(s) for s in segs] == [1, 1]
    assert segs[0] == [early]
    assert segs[1] == [late]


def test_last_gap_segment_tiebreaks_equal_close_ts() -> None:
    """List [116, 100] same close_ts: priors[-1] without open_ts sort is 100 — false jump into current."""
    close = datetime(2026, 8, 30, 12, 15, tzinfo=UTC)
    early = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    late = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=close,
        open=Decimal("116"),
        high=Decimal("117"),
        low=Decimal("115"),
        close=Decimal("116"),
    )
    current = _bar(17, close="116", open_="116")
    assert early.close_ts == late.close_ts
    assert current.close_ts < T
    assert abs(current.open - late.close) / late.close < JUMP_RATIO_15M
    assert abs(current.open - early.close) / early.close > JUMP_RATIO_15M
    assert last_gap_segment([late, early], current, t=T) == [late]


def test_split_on_gaps_orders_by_close_not_open() -> None:
    """Early-open late-close at 100, then a 116 that closes first. Open-order is a 16% gap."""
    long = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 45, tzinfo=UTC),
        open=Decimal("116"),
        high=Decimal("117"),
        low=Decimal("115"),
        close=Decimal("116"),
    )
    assert long.open_ts < mid.open_ts
    assert mid.close_ts < long.close_ts
    assert abs(mid.open - long.close) / long.close > JUMP_RATIO_15M
    assert abs(long.open - mid.close) / mid.close < JUMP_RATIO_15M
    segs = split_on_gaps([long, mid])
    assert [len(s) for s in segs] == [2]
    assert segs[0] == [mid, long]


def test_last_gap_segment_orders_by_close_not_open() -> None:
    """Open-order last is 116 — current at 100 looks like a jump. Close-order last is 100."""
    long = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 45, tzinfo=UTC),
        open=Decimal("116"),
        high=Decimal("117"),
        low=Decimal("115"),
        close=Decimal("116"),
    )
    current = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert current.close_ts < T
    assert abs(current.open - long.close) / long.close < JUMP_RATIO_15M
    # 16/116 < 15%: not a jump into current. Open-order split still ends on [mid] alone.
    assert abs(current.open - mid.close) / mid.close < JUMP_RATIO_15M
    assert last_gap_segment([long, mid], current, t=T) == [mid, long]


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


def test_atr_sorts_before_the_last_window() -> None:
    """Last 15 in list order is not last in time. An early wide bar at the end must not enter ATR."""
    tight = [_bar(i, close="101", open_="101") for i in range(15)]
    early = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 8, 15, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("90"),
        low=Decimal("80"),
        close=Decimal("80"),
    )
    mixed = tight + [early]
    last_tr = max(
        early.high - early.low,
        abs(early.high - tight[-1].close),
        abs(early.low - tight[-1].close),
    )
    list_order = (Decimal("2") * Decimal("13") + last_tr) / Decimal("14")
    assert mixed[-1].close == Decimal("80")
    assert list_order == Decimal("47") / Decimal("14")
    assert atr(tight) == Decimal("2")
    assert atr([early] + tight) == Decimal("2")
    assert atr(mixed) == Decimal("2")
    assert atr(mixed) != list_order


def test_atr_rejects_mixed_symbol_and_tf() -> None:
    """A late ETH wide bar is last in time. Without a same-series guard ATR becomes 47/14."""
    tight = [_bar(i, close="101", open_="101") for i in range(15)]
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("90"),
        low=Decimal("80"),
        close=Decimal("80"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 17, 0, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("90"),
        low=Decimal("80"),
        close=Decimal("80"),
    )
    last_tr = max(
        eth.high - eth.low,
        abs(eth.high - tight[-1].close),
        abs(eth.low - tight[-1].close),
    )
    polluted = (Decimal("2") * Decimal("13") + last_tr) / Decimal("14")
    assert atr(tight) == Decimal("2")
    assert polluted == Decimal("47") / Decimal("14")
    with pytest.raises(ValueError, match="one symbol"):
        atr(tight + [eth])
    with pytest.raises(ValueError, match="one"):
        atr(tight + [hourly])


def test_atr_equal_close_ts_orders_by_open() -> None:
    """Same close_ts: only close_ts sort is stable and keeps list order. Open-order A then B is 75/14."""
    start = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    tight = []
    for i in range(13):
        ts = start + timedelta(minutes=15 * i)
        tight.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    close_at = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    early_open = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=close_at,
        open=Decimal("80"),
        high=Decimal("80"),
        low=Decimal("80"),
        close=Decimal("80"),
    )
    late_open = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 30, tzinfo=UTC),
        close_ts=close_at,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("100"),
    )
    expect = Decimal("75") / Decimal("14")
    list_ba = Decimal("64") / Decimal("14")
    assert early_open.open_ts < late_open.open_ts
    assert early_open.close_ts == late_open.close_ts
    assert atr(tight + [early_open, late_open]) == expect
    assert atr(tight + [late_open, early_open]) == expect
    assert expect != list_ba


def test_atr_is_mean_true_range_not_median_or_high_low() -> None:
    """14% open is not a gap. TR=14 then 13×2: mean 40/14. Median TR=2. Mean high-low=27/14."""
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    bars = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=start,
            close_ts=start + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
    ]
    ts = start + timedelta(minutes=15)
    bars.append(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=ts,
            close_ts=ts + timedelta(minutes=15),
            open=Decimal("114"),
            high=Decimal("114"),
            low=Decimal("113"),
            close=Decimal("114"),
        )
    )
    for i in range(2, 15):
        ts = start + timedelta(minutes=15 * i)
        bars.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("114"),
                high=Decimal("116"),
                low=Decimal("114"),
                close=Decimal("114"),
            )
        )
    assert abs(bars[1].open - bars[0].close) / bars[0].close == Decimal("0.14")
    assert (bars[1].high - bars[1].low) == Decimal("1")
    assert atr(bars) == Decimal("40") / Decimal("14")
    assert atr(bars) != Decimal("2")
    assert atr(bars) != Decimal("27") / Decimal("14")


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


def test_plus530_t_does_not_stagnate_a_1315z_bar() -> None:
    """+3 16:45 is 13:45Z — five same closes are a fact. +5:30 16:45 is 11:15Z. Hardcoded -3 would STAGNANT."""
    plus3 = timezone(timedelta(hours=3))
    plus530 = timezone(timedelta(hours=5, minutes=30))
    t3 = datetime(2026, 8, 30, 16, 45, tzinfo=plus3)
    t530 = datetime(2026, 8, 30, 16, 45, tzinfo=plus530)
    hist = [_bar(i, close="100") for i in range(4)]
    current = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert t3.astimezone(UTC) == datetime(2026, 8, 30, 13, 45, tzinfo=UTC)
    assert t530.astimezone(UTC) == datetime(2026, 8, 30, 11, 15, tzinfo=UTC)
    assert classify_bar_quality(hist, current, t=t3) == STAGNANT
    assert classify_bar_quality(hist, current, t=t530) == LIVE
    assert last_gap_segment(hist, current, t=t530) == []


def test_plus9_close_ts_is_closed_at_utc_noon() -> None:
    """+9 16:30 close is 07:30Z. Clock 16:30 > 12:00 would keep a closed bar LIVE."""
    plus9 = timezone(timedelta(hours=9))
    t = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    start = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)
    hist = []
    for i in range(4):
        ts = start + timedelta(minutes=15 * i)
        hist.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            )
        )
    current = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=plus9),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=plus9),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert current.close_ts.hour == 16
    assert t.hour == 12
    assert current.close_ts < t
    assert classify_bar_quality(hist, current, t=t) == STAGNANT
    assert last_gap_segment(hist, current, t=t) == hist


def test_plus9_prior_completes_stagnant() -> None:
    """+9 16:30 prior is 07:30Z. Clock 16:30 > 08:00 current would leave only four same closes."""
    plus9 = timezone(timedelta(hours=9))
    t = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    start = datetime(2026, 8, 30, 6, 30, tzinfo=UTC)
    hist = []
    for i in range(3):
        ts = start + timedelta(minutes=15 * i)
        hist.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            )
        )
    off = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=plus9),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=plus9),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    current = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 7, 45, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert off.close_ts.hour == 16
    assert current.close_ts.hour == 8
    assert off.close_ts < current.close_ts
    assert classify_bar_quality(hist, current, t=t) == LIVE
    assert classify_bar_quality(hist + [off], current, t=t) == STAGNANT


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


def test_foreign_symbol_last_in_time_does_not_fake_a_jump_into_current() -> None:
    """15 BTC at 101 + later ETH at 80. Mixed last-prior is a >15% jump. Same-series last is not."""
    priors = [_bar(i, close="101", open_="101") for i in range(15)]
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    current = _bar(17, close="101", open_="101")
    assert priors[-1].close_ts < eth.close_ts < current.close_ts
    assert abs(current.open - eth.close) / eth.close > JUMP_RATIO_15M
    assert abs(current.open - priors[-1].close) / priors[-1].close < JUMP_RATIO_15M
    assert last_gap_segment(priors, current, t=T) == priors
    assert last_gap_segment(priors + [eth], current, t=T) == priors


def test_foreign_tf_last_in_time_does_not_fake_a_jump_into_current() -> None:
    """15 15m at 101 + later 1h at 80. Mixed last-prior is a >15% jump. Same-tf last is not."""
    priors = [_bar(i, close="101", open_="101") for i in range(15)]
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    current = _bar(17, close="101", open_="101")
    assert priors[-1].close_ts < hourly.close_ts < current.close_ts
    assert abs(current.open - hourly.close) / hourly.close > JUMP_RATIO_15M
    assert last_gap_segment(priors, current, t=T) == priors
    assert last_gap_segment(priors + [hourly], current, t=T) == priors


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


def test_foreign_symbol_last_in_time_does_not_hide_a_real_jump() -> None:
    """15 BTC at 130 + later ETH at 100. Mixed last-prior has no jump. Same-series last does."""
    priors = [_bar(i, close="130", open_="130") for i in range(15)]
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    current = _bar(17, close="100", open_="100")
    assert priors[-1].close_ts < eth.close_ts < current.close_ts
    assert abs(current.open - priors[-1].close) / priors[-1].close > JUMP_RATIO_15M
    assert abs(current.open - eth.close) / eth.close < JUMP_RATIO_15M
    assert last_gap_segment(priors, current, t=T) == []
    assert last_gap_segment(priors + [eth], current, t=T) == []


def test_foreign_tf_last_in_time_does_not_hide_a_real_jump() -> None:
    """15 15m at 130 + later 1h at 100. Mixed last-prior has no jump. Same-tf last does."""
    priors = [_bar(i, close="130", open_="130") for i in range(15)]
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    current = _bar(17, close="100", open_="100")
    assert priors[-1].close_ts < hourly.close_ts < current.close_ts
    assert abs(current.open - hourly.close) / hourly.close < JUMP_RATIO_15M
    assert last_gap_segment(priors, current, t=T) == []
    assert last_gap_segment(priors + [hourly], current, t=T) == []


def test_eth_real_jump_is_not_hidden_by_later_btc() -> None:
    """Hardcoded `history is BTC` keeps only BTC 100 — no jump into the ETH current."""
    priors = [_bar(i, close="130", open_="130", symbol="ETHUSDT") for i in range(15)]
    btc = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    current = _bar(17, close="100", open_="100", symbol="ETHUSDT")
    assert priors[-1].close_ts < btc.close_ts < current.close_ts
    assert last_gap_segment(priors, current, t=T) == []
    assert last_gap_segment(priors + [btc], current, t=T) == []


def test_hourly_real_jump_is_not_hidden_by_later_15m() -> None:
    """Hardcoded `tf==15m` keeps only the late 15m 100 — no jump into the 1h current."""
    priors = []
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(15):
        ts = start + timedelta(hours=i)
        priors.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ts,
                close_ts=ts + timedelta(hours=1),
                open=Decimal("130"),
                high=Decimal("131"),
                low=Decimal("129"),
                close=Decimal("130"),
            )
        )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    current = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert priors[-1].close_ts < foreign.close_ts < current.close_ts
    assert current.close_ts < T
    assert abs(current.open - priors[-1].close) / priors[-1].close > JUMP_RATIO_15M
    assert last_gap_segment(priors, current, t=T) == []
    assert last_gap_segment(priors + [foreign], current, t=T) == []


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


def test_15m_zero_volume_does_not_illiquid_a_1h_bar() -> None:
    """Hardcoded `tf==15m` would ILLIQUID a 1h print. Filter is current.tf."""
    hist = [_bar(0, close="100", volume=Decimal("0"))]
    current = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    assert current.close_ts < T
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(hist, _bar(1, close="101", volume=Decimal("0")), t=T) == ILLIQUID


def test_other_symbol_zero_volume_is_not_illiquid() -> None:
    hist = [_bar(0, close="100", symbol="ETHUSDT", volume=Decimal("0"))]
    current = _bar(1, close="101", volume=Decimal("0"))
    assert prior_same_tf(hist, current, t=T) == []
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_illiquid_last_two_does_not_use_foreign_symbol_zero_as_neighbor() -> None:
    """15m BTC vol=1 + 15m ETH vol=0 + current 15m BTC vol=0. Mixed last-2 is two zeros."""
    hist = [
        _bar(0, close="100", volume=Decimal("1")),
        _bar(1, close="100", symbol="ETHUSDT", volume=Decimal("0")),
    ]
    current = _bar(2, close="101", volume=Decimal("0"))
    assert classify_bar_quality([hist[0]], current, t=T) == LIVE
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(
        [_bar(1, close="100", volume=Decimal("0"))],
        current,
        t=T,
    ) == ILLIQUID


def test_illiquid_last_two_ignores_foreign_symbol_volume_between_zeros() -> None:
    """BTC vol=0 + ETH vol=1 + current BTC vol=0. Mixed last-2 is vol=1 + 0 → LIVE."""
    hist = [
        _bar(0, close="100", volume=Decimal("0")),
        _bar(1, close="100", symbol="ETHUSDT", volume=Decimal("1")),
    ]
    current = _bar(2, close="101", volume=Decimal("0"))
    assert classify_bar_quality([hist[0]], current, t=T) == ILLIQUID
    assert classify_bar_quality(hist, current, t=T) == ILLIQUID


def test_illiquid_last_two_does_not_fill_none_volume_with_foreign_zero() -> None:
    """Same-tf neighbor volume=None is not a zero. Mixed last-2 is ETH 0 + current 0."""
    hist = [
        _bar(0, close="100", volume=None),
        _bar(1, close="100", symbol="ETHUSDT", volume=Decimal("0")),
    ]
    current = _bar(2, close="101", volume=Decimal("0"))
    assert hist[0].volume is None
    assert classify_bar_quality([hist[0]], current, t=T) == LIVE
    assert classify_bar_quality(hist, current, t=T) == LIVE


def test_illiquid_last_two_ignores_foreign_tf_volume_between_zeros() -> None:
    """15m vol=0 + 1h vol=1 closing after it + current 15m vol=0. Mixed last-2 is vol=1 + 0."""
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 20, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    hist = [_bar(0, close="100", volume=Decimal("0")), hourly]
    current = _bar(2, close="101", volume=Decimal("0"))
    assert _bar(0).close_ts < hourly.close_ts < current.close_ts
    assert classify_bar_quality([hist[0]], current, t=T) == ILLIQUID
    assert classify_bar_quality(hist, current, t=T) == ILLIQUID


def test_eth_illiquid_last_two_ignores_btc_volume_between_zeros() -> None:
    """Hardcoded `history is BTC` takes BTC vol=1 + ETH current vol=0 as last-2 → LIVE."""
    hist = [
        _bar(0, close="100", symbol="ETHUSDT", volume=Decimal("0")),
        _bar(1, close="100", volume=Decimal("1")),
    ]
    current = _bar(2, close="101", symbol="ETHUSDT", volume=Decimal("0"))
    assert classify_bar_quality([hist[0]], current, t=T) == ILLIQUID
    assert classify_bar_quality(hist, current, t=T) == ILLIQUID


def test_hourly_illiquid_last_two_ignores_15m_volume_between_zeros() -> None:
    """Hardcoded `tf==15m` takes 15m vol=1 + 1h current vol=0 as last-2 → LIVE."""
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    current = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 14, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < current.close_ts
    assert current.close_ts < T
    assert classify_bar_quality([neighbor], current, t=T) == ILLIQUID
    assert classify_bar_quality([neighbor, foreign], current, t=T) == ILLIQUID


def test_illiquid_last_two_does_not_use_foreign_tf_zero_as_neighbor() -> None:
    """15m vol=1 + 1h vol=0 closing after it + current 15m vol=0. Mixed last-2 is two zeros."""
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 20, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("0"),
    )
    hist = [_bar(0, close="100", volume=Decimal("1")), hourly]
    current = _bar(2, close="101", volume=Decimal("0"))
    assert _bar(0).close_ts < hourly.close_ts < current.close_ts
    assert classify_bar_quality([hist[0]], current, t=T) == LIVE
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(
        [_bar(1, close="100", volume=Decimal("0"))],
        current,
        t=T,
    ) == ILLIQUID


def test_eth_illiquid_last_two_does_not_use_btc_zero_as_neighbor() -> None:
    """Hardcoded `history is BTC` takes BTC vol=0 + ETH current vol=0 as last-2."""
    hist = [
        _bar(0, close="100", symbol="ETHUSDT", volume=Decimal("1")),
        _bar(1, close="100", volume=Decimal("0")),
    ]
    current = _bar(2, close="101", symbol="ETHUSDT", volume=Decimal("0"))
    assert classify_bar_quality([hist[0]], current, t=T) == LIVE
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(
        [_bar(1, close="100", symbol="ETHUSDT", volume=Decimal("0"))],
        current,
        t=T,
    ) == ILLIQUID


def test_hourly_illiquid_last_two_does_not_use_15m_zero_as_neighbor() -> None:
    """Hardcoded `tf==15m` takes 15m vol=0 + 1h current vol=0 as last-2."""
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("0"),
    )
    current = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 13, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 14, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < current.close_ts
    assert current.close_ts < T
    assert classify_bar_quality([neighbor], current, t=T) == LIVE
    assert classify_bar_quality([neighbor, foreign], current, t=T) == LIVE
    assert classify_bar_quality([foreign], current, t=T) == LIVE


def test_btc_zero_volume_does_not_illiquid_an_eth_bar() -> None:
    """Hardcoded `history is BTC` would ILLIQUID an ETH print. Filter is current.symbol."""
    hist = [_bar(0, close="100", volume=Decimal("0"))]
    current = _bar(1, close="101", symbol="ETHUSDT", volume=Decimal("0"))
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(hist, _bar(1, close="101", volume=Decimal("0")), t=T) == ILLIQUID


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


def test_bar_closing_during_current_is_an_illiquid_neighbor() -> None:
    """close_ts < current.close_ts is a last-2 prior even after current.open. `< open_ts` would stay LIVE."""
    current = _bar(17, close="101", volume=Decimal("0"))
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 25, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    assert current.open_ts < mid.close_ts < current.close_ts
    assert classify_bar_quality([], current, t=T) == LIVE
    assert classify_bar_quality([mid], current, t=T) == ILLIQUID


def test_bar_closing_during_current_breaks_illiquid_last_two() -> None:
    """Earlier zero + mid vol=1 + current zero. Dropping mid makes last-2 two zeros → false ILLIQUID."""
    early = _bar(16, close="101", volume=Decimal("0"))
    current = _bar(17, close="101", volume=Decimal("0"))
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 25, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    assert early.close_ts < mid.close_ts < current.close_ts
    assert current.open_ts < mid.close_ts
    assert classify_bar_quality([early], current, t=T) == ILLIQUID
    assert classify_bar_quality([early, mid], current, t=T) == LIVE


def test_bar_closing_during_current_is_a_stagnant_prior() -> None:
    """3 early same + mid same + current same is last-5. `< open_ts` would leave 4 and stay LIVE."""
    hist = [_bar(i, close="100") for i in range(3)]
    current = _bar(17, close="100")
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 25, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    assert current.open_ts < mid.close_ts < current.close_ts
    assert classify_bar_quality(hist, current, t=T) == LIVE
    assert classify_bar_quality(hist + [mid], current, t=T) == STAGNANT


def test_bar_closing_during_current_can_hide_a_real_jump() -> None:
    """15 at 101 + mid at 80 during current. `< open_ts` would keep the old segment."""
    priors = [_bar(i, close="101", open_="101") for i in range(15)]
    current = _bar(17, close="100", open_="100")
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 25, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    assert current.open_ts < mid.close_ts < current.close_ts
    assert abs(current.open - priors[-1].close) / priors[-1].close < JUMP_RATIO_15M
    assert abs(current.open - mid.close) / mid.close > JUMP_RATIO_15M
    assert len(last_gap_segment(priors, current, t=T)) == 15
    assert last_gap_segment(priors + [mid], current, t=T) == []


def test_illiquid_last_two_tiebreaks_equal_close_ts_by_open() -> None:
    """Same close_ts: close-only sort is stable and keeps [vol1, vol0] — last-2 two zeros."""
    close = datetime(2026, 8, 30, 12, 15, tzinfo=UTC)
    early_zero = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("0"),
    )
    late_vol = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    current = _bar(2, close="102", volume=Decimal("0"))
    assert early_zero.close_ts == late_vol.close_ts
    assert early_zero.open_ts < late_vol.open_ts
    assert classify_bar_quality([late_vol, early_zero], current, t=T) == LIVE
    assert classify_bar_quality([early_zero, late_vol], current, t=T) == LIVE


def test_illiquid_last_two_tiebreaks_equal_close_ts_keeps_later_zero() -> None:
    """Later-open zero is the neighbor. Close-only sort of [zero, vol1] would take the early vol=1."""
    close = datetime(2026, 8, 30, 12, 15, tzinfo=UTC)
    early_vol = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    late_zero = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    current = _bar(2, close="102", volume=Decimal("0"))
    assert early_vol.close_ts == late_zero.close_ts
    assert classify_bar_quality([late_zero, early_vol], current, t=T) == ILLIQUID
    assert classify_bar_quality([early_vol, late_zero], current, t=T) == ILLIQUID


def test_stagnant_last_five_tiebreaks_equal_close_ts_by_open() -> None:
    """Early-open 101 + later-open 100 share close_ts. Close-only [100, 101] puts 101 in last-5."""
    close = datetime(2026, 8, 30, 12, 15, tzinfo=UTC)
    early_break = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    late_same = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 10, tzinfo=UTC),
        close_ts=close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
    )
    later = [_bar(i, close="100") for i in range(1, 4)]
    current = _bar(4, close="100")
    assert early_break.close_ts == late_same.close_ts
    assert early_break.close_ts < later[0].close_ts
    assert classify_bar_quality([late_same, early_break, *later], current, t=T) == STAGNANT
    assert classify_bar_quality([early_break, late_same, *later], current, t=T) == STAGNANT


def test_illiquid_last_two_orders_by_close_not_open() -> None:
    """Long bar closes last with volume. Open-order last-2 would be the earlier-close zero."""
    long_vol = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    short_zero = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 45, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    current = _bar(17, close="102", volume=Decimal("0"))
    assert short_zero.open_ts > long_vol.open_ts
    assert short_zero.close_ts < long_vol.close_ts < current.close_ts
    assert classify_bar_quality([long_vol, short_zero], current, t=T) == LIVE
    assert classify_bar_quality([short_zero, long_vol], current, t=T) == LIVE


def test_bar_closing_during_current_breaks_stagnant_last_five() -> None:
    """4 same + mid different close during current. `< open_ts` would stagnate on the four + current."""
    hist = [_bar(i, close="100") for i in range(4)]
    current = _bar(17, close="100")
    mid = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 25, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    assert current.open_ts < mid.close_ts < current.close_ts
    assert classify_bar_quality(hist, current, t=T) == STAGNANT
    assert classify_bar_quality(hist + [mid], current, t=T) == LIVE
