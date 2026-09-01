"""Width journal: PIT rank, gap segment, n<20 → None. Not size."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from capitalizator.patterns.bar_quality import atr, last_gap_segment, prior_same_tf
from capitalizator.patterns.width import (
    WidthSample,
    width_now,
    width_now_from_history,
    width_rank,
)
from capitalizator.zones.model import Bar

T0 = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)


def _bar(i: int, *, high: str = "102", low: str = "100", open_: str | None = None, close: str | None = None) -> Bar:
    ts = T0 + timedelta(minutes=15 * i)
    hi, lo = Decimal(high), Decimal(low)
    mid = (hi + lo) / Decimal("2")
    op = Decimal(open_) if open_ is not None else mid
    cl = Decimal(close) if close is not None else mid
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=ts,
        close_ts=ts + timedelta(minutes=15),
        open=op,
        high=hi,
        low=lo,
        close=cl,
    )


def _sample(i: int, w: str, *, zone: str = "z1") -> WidthSample:
    return WidthSample(zone_id=zone, ts=T0 + timedelta(minutes=i), w_now=Decimal(w))


def test_width_now_is_range_over_atr() -> None:
    bar = _bar(0, high="103", low="101")
    assert width_now(bar, Decimal("2")) == Decimal("1")
    assert width_now(bar, None) is None
    assert width_now(bar, Decimal("0")) is None


def test_width_from_history_uses_post_gap_segment() -> None:
    hist = [_bar(i) for i in range(15)]
    bar = _bar(20, high="100.2", low="100.1")
    assert width_now_from_history(bar, hist, t=NOW) == Decimal("0.1") / Decimal("2")
    # 17 pre-gap + 3 post-gap = 20. Combined ATR exists; a 4-bar fixture
    # would be None even without a split and does not lock the cut.
    pre = [_bar(i, open_="80", close="80", high="81", low="79") for i in range(17)]
    post = [_bar(i, open_="101", close="101") for i in range(17, 20)]
    gapped = pre + post
    assert len(gapped) == 20
    assert atr(gapped) is not None
    assert abs(bar.open - post[-1].close) / post[-1].close < Decimal("0.15")
    assert len(last_gap_segment(gapped, bar, t=NOW)) == 3
    assert width_now_from_history(bar, gapped, t=NOW) is None
    long_post = [_bar(i, open_="80", close="80", high="81", low="79") for i in range(5)] + [
        _bar(i, open_="101", close="101") for i in range(5, 20)
    ]
    assert len(last_gap_segment(long_post, bar, t=NOW)) == 15
    assert width_now_from_history(bar, long_post, t=NOW) == Decimal("0.1") / Decimal("2")


def test_offset_t_has_no_width_on_later_utc_bar() -> None:
    """+3 16:45 is 13:45Z. Clock 16:30<16:45 would journal width on an open bar."""
    plus3 = timezone(timedelta(hours=3))
    t = datetime(2026, 8, 30, 16, 45, tzinfo=plus3)
    hist = [_bar(i) for i in range(15)]
    bar = _bar(17, high="100.2", low="100.1")
    assert bar.close_ts == datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    assert width_now_from_history(bar, hist, t=NOW) == Decimal("0.1") / Decimal("2")
    assert width_now_from_history(bar, hist, t=t) is None
    assert last_gap_segment(hist, bar, t=t) == []


def test_early_gap_appended_last_still_has_width() -> None:
    """An early 80 stuffed at list end must not look like a jump into the current bar."""
    hist = [_bar(i) for i in range(15)]
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
    bar = _bar(20, high="100.2", low="100.1")
    mixed = hist + [early]
    assert mixed[-1].close == Decimal("80")
    assert abs(bar.open - mixed[-1].close) / mixed[-1].close > Decimal("0.15")
    assert width_now_from_history(bar, hist, t=NOW) == Decimal("0.1") / Decimal("2")
    assert width_now_from_history(bar, mixed, t=NOW) == Decimal("0.1") / Decimal("2")


def test_unclosed_bar_has_no_width() -> None:
    """Range is not a fact until close_ts < t. Do not journal a forming bar."""
    hist = [_bar(i) for i in range(15)]
    forming = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=NOW - timedelta(minutes=15),
        close_ts=NOW,
        open=Decimal("100.15"),
        high=Decimal("100.2"),
        low=Decimal("100.1"),
        close=Decimal("100.15"),
    )
    assert forming.close_ts >= NOW
    assert last_gap_segment(hist, forming, t=NOW) == []
    assert width_now_from_history(forming, hist, t=NOW) is None


def test_exact_15pct_into_current_still_has_width() -> None:
    """Equality is not a gap. A `>= 15%` cut would drop the 15-bar ATR and yield None."""
    hist = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=T0 + timedelta(minutes=15 * i),
            close_ts=T0 + timedelta(minutes=15 * i + 15),
            open=Decimal("100"),
            high=Decimal("120"),
            low=Decimal("80"),
            close=Decimal("100"),
        )
        for i in range(15)
    ]
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=T0 + timedelta(minutes=15 * 20),
        close_ts=T0 + timedelta(minutes=15 * 20 + 15),
        open=Decimal("115"),
        high=Decimal("115"),
        low=Decimal("100.1"),
        close=Decimal("100.15"),
    )
    assert abs(bar.open - hist[-1].close) / hist[-1].close == Decimal("0.15")
    assert len(last_gap_segment(hist, bar, t=NOW)) == 15
    assert width_now_from_history(bar, hist, t=NOW) == (bar.high - bar.low) / Decimal("40")


def test_hourly_history_does_not_make_width() -> None:
    """15 same-symbol 1h bars would yield ATR if the tf filter dropped."""
    hourly = []
    for i in range(15):
        ht = datetime(2026, 8, 29, 0, 0, tzinfo=UTC) + timedelta(hours=i)
        hourly.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ht,
                close_ts=ht + timedelta(minutes=59),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(20, high="100.2", low="100.1")
    assert sum(1 for b in hourly if b.close_ts < bar.close_ts) == 15
    assert atr(hourly) == Decimal("2")
    assert prior_same_tf(hourly, bar, t=NOW) == []
    assert width_now_from_history(bar, hourly, t=NOW) is None


def test_gap_into_current_width_is_none() -> None:
    hist = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=T0 + timedelta(minutes=15 * i),
            close_ts=T0 + timedelta(minutes=15 * i + 15),
            open=Decimal("130"),
            high=Decimal("131"),
            low=Decimal("129"),
            close=Decimal("130"),
        )
        for i in range(15)
    ]
    bar = _bar(20, high="100.2", low="100.1", open_="100.15", close="100.15")
    assert abs(bar.open - hist[-1].close) / hist[-1].close > Decimal("0.15")
    assert width_now_from_history(bar, hist, t=NOW) is None


def test_rank_needs_twenty_priors() -> None:
    hist = [_sample(i, "1") for i in range(19)]
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("2"), history=hist) is None
    hist.append(_sample(19, "1"))
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("2"), history=hist) == Decimal("1")


def test_rank_is_share_of_strictly_smaller() -> None:
    hist = [_sample(i, "1") for i in range(10)] + [_sample(10 + i, "3") for i in range(10)]
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("2"), history=hist) == Decimal("10") / Decimal(
        "20"
    )
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("1"), history=hist) == Decimal("0")


def test_other_zone_is_not_a_prior() -> None:
    hist = [_sample(i, "1", zone="z2") for i in range(20)]
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("2"), history=hist) is None


def test_future_sample_is_invisible() -> None:
    hist = [_sample(i, "1") for i in range(20)]
    cut = T0 + timedelta(minutes=19)
    assert width_rank(zone_id="z1", now=cut, w_now=Decimal("2"), history=hist) is None
    hist.append(_sample(100, "0.1"))
    later = T0 + timedelta(minutes=20)
    assert width_rank(zone_id="z1", now=later, w_now=Decimal("2"), history=hist) == Decimal("1")


def test_two_runs_same_rank() -> None:
    hist = [_sample(i, str(i)) for i in range(20)]

    def run() -> Decimal | None:
        return width_rank(zone_id="z1", now=NOW, w_now=Decimal("10"), history=hist)

    assert run() == run()
    assert run() == Decimal("10") / Decimal("20")


def test_negative_w_now_rejected() -> None:
    with pytest.raises(ValueError, match="w_now"):
        width_rank(zone_id="z1", now=NOW, w_now=Decimal("-1"), history=[])
    with pytest.raises(ValueError, match="w_now"):
        WidthSample(zone_id="z1", ts=T0, w_now=Decimal("-1"))


def test_naive_t_is_rejected() -> None:
    with pytest.raises(TypeError, match="naive"):
        width_now_from_history(_bar(0), [], t=datetime(2026, 8, 30, 18, 0))


def test_naive_now_is_rejected() -> None:
    hist = [_sample(i, "1") for i in range(20)]
    with pytest.raises(TypeError, match="naive"):
        width_rank(zone_id="z1", now=datetime(2026, 8, 30, 18, 0), w_now=Decimal("2"), history=hist)


def test_sample_at_now_is_not_a_prior() -> None:
    hist = [_sample(i, "1") for i in range(19)]
    hist.append(WidthSample(zone_id="z1", ts=NOW, w_now=Decimal("1")))
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("2"), history=hist) is None


def test_later_bar_does_not_complete_width() -> None:
    """14 priors + a bar that closes after current but before t would ATR if lookahead leaked."""
    fourteen = [_bar(i) for i in range(14)]
    later = _bar(21)
    bar = _bar(20, high="100.2", low="100.1")
    assert later.close_ts > bar.close_ts
    assert later.close_ts < NOW
    assert atr(fourteen + [later]) == Decimal("2")
    assert width_now_from_history(bar, fourteen, t=NOW) is None
    assert width_now_from_history(bar, fourteen + [later], t=NOW) is None


def test_labeled_bar_in_history_does_not_complete_width() -> None:
    fourteen = [_bar(i) for i in range(14)]
    bar = _bar(20, high="100.2", low="100.1")
    assert atr(fourteen + [bar]) is not None
    assert width_now_from_history(bar, fourteen, t=NOW) is None
    assert width_now_from_history(bar, fourteen + [bar], t=NOW) is None


def test_foreign_symbol_history_does_not_make_width() -> None:
    hist = []
    for i in range(15):
        ts = T0 + timedelta(minutes=15 * i)
        hist.append(
            Bar(
                symbol="ETHUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts + timedelta(minutes=15),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(20, high="100.2", low="100.1")
    assert sum(1 for b in hist if b.close_ts < bar.close_ts) == 15
    assert atr(hist) == Decimal("2")
    assert prior_same_tf(hist, bar, t=NOW) == []
    assert width_now_from_history(bar, hist, t=NOW) is None


def test_offset_timezone_sample_counts_by_utc_instant() -> None:
    """+3 16:30 is 13:30Z. Clock hour 16 vs now 14:00Z would drop a real prior."""
    plus3 = timezone(timedelta(hours=3))
    now = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    hist = [_sample(i, "1") for i in range(19)]
    off = WidthSample(
        zone_id="z1",
        ts=datetime(2026, 8, 30, 16, 30, tzinfo=plus3),
        w_now=Decimal("1"),
    )
    assert off.ts.hour == 16
    assert now.hour == 14
    assert off.ts < now
    assert width_rank(zone_id="z1", now=now, w_now=Decimal("2"), history=hist) is None
    assert width_rank(zone_id="z1", now=now, w_now=Decimal("2"), history=hist + [off]) == Decimal("1")


def test_offset_timezone_sample_at_now_is_not_a_prior() -> None:
    plus3 = timezone(timedelta(hours=3))
    now = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    hist = [_sample(i, "1") for i in range(19)]
    off = WidthSample(
        zone_id="z1",
        ts=datetime(2026, 8, 30, 16, 30, tzinfo=plus3),
        w_now=Decimal("1"),
    )
    assert off.ts == now
    assert width_rank(zone_id="z1", now=now, w_now=Decimal("2"), history=hist + [off]) is None


def test_offset_now_does_not_see_later_utc_sample() -> None:
    """+3 16:30 is 13:30Z. Clock 14:00<16:30 would count a 14:00Z sample that is still future."""
    plus3 = timezone(timedelta(hours=3))
    now = datetime(2026, 8, 30, 16, 30, tzinfo=plus3)
    hist = [_sample(i, "1") for i in range(19)]
    late = WidthSample(
        zone_id="z1",
        ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        w_now=Decimal("1"),
    )
    assert late.ts.hour == 14
    assert now.hour == 16
    assert late.ts >= now
    assert width_rank(zone_id="z1", now=now, w_now=Decimal("2"), history=hist) is None
    assert width_rank(zone_id="z1", now=now, w_now=Decimal("2"), history=hist + [late]) is None


def test_naive_width_sample_rejected() -> None:
    with pytest.raises(TypeError, match="naive"):
        WidthSample(zone_id="z1", ts=datetime(2026, 8, 30, 12, 0), w_now=Decimal("1"))
