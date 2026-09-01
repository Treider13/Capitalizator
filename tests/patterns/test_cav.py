"""CAV: closed bar only. Wick+close inside = REJECT. Close beyond = THROUGH."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from capitalizator.patterns.bar_quality import prior_same_tf
from capitalizator.patterns.cav import label
from capitalizator.zones.model import Bar, Zone

T = datetime(2026, 8, 30, 16, 45, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="15m",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="swing",
    created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
)


def _bar(*, low: str, high: str, close: str, close_ts: datetime | None = None) -> Bar:
    end = close_ts or datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=end,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_naive_t_is_rejected() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1")
    with pytest.raises(TypeError, match="naive"):
        label(ZONE, bar, t=datetime(2026, 8, 30, 16, 45), htf_bias="box")


def test_unclosed_bar_is_noise() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1", close_ts=T)
    assert label(ZONE, bar, t=T, htf_bias="box") == "NOISE"


def test_unclosed_with_compress_history_is_still_noise() -> None:
    """Forming bar must not become COMPRESS even if 15 priors would allow it."""
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10", close_ts=T)
    assert bar.close_ts >= T
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_wick_in_close_inside_is_reject() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box") == label(ZONE, bar, t=T, htf_bias="box")


def test_close_beyond_support_is_through() -> None:
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"


def test_htf_against_is_noise() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="short") == "NOISE"


def test_mid_range_miss_is_noise() -> None:
    bar = _bar(low="110", high="111", close="110.5")
    assert label(ZONE, bar, t=T, htf_bias="box") == "NOISE"


def test_close_inside_without_wick_beyond_is_drift() -> None:
    """INVENTION-JURY: in the zone, no reject, no close beyond → DRIFT."""
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"


def test_labeled_bar_in_history_does_not_complete_atr() -> None:
    """14 priors: no ATR. Putting the labeled bar into closed_bars must not make the 15th."""
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(14):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [bar]) == "DRIFT"


def test_reversed_history_still_compresses() -> None:
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=list(reversed(closed))) == "COMPRESS"


def test_early_gap_appended_last_still_compresses() -> None:
    """Identical-TR reverse does not lock sort. An early 80 at list end is a false gap if unsorted."""
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    closed = []
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
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
    bar = _bar(low="100.05", high="100.15", close="100.10")
    mixed = closed + [early]
    assert mixed[-1].close == Decimal("80")
    assert abs(bar.open - mixed[-1].close) / mixed[-1].close > Decimal("0.15")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=mixed) == "COMPRESS"


def _atr15(*, close: str = "101") -> list[Bar]:
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    px = Decimal(close)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=px,
                high=px + Decimal("1"),
                low=px - Decimal("1"),
                close=px,
            )
        )
    return closed


def test_small_range_inside_zone_is_compress() -> None:
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "COMPRESS"


def test_range_equal_to_atr_is_drift_not_compress() -> None:
    """COMPRESS is range < ATR, not <=. Body is 0 here — |close−open| < ATR would fake COMPRESS."""
    bar = _bar(low="100.0", high="102.0", close="100.10")
    assert (bar.high - bar.low) == Decimal("2")
    assert abs(bar.close - bar.open) == Decimal("0")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "DRIFT"


def test_offset_t_does_not_close_a_later_utc_bar() -> None:
    """+3 16:45 is 13:45Z. Clock 16:30<16:45 would COMPRESS a bar that is still open."""
    plus3 = timezone(timedelta(hours=3))
    t = datetime(2026, 8, 30, 16, 45, tzinfo=plus3)
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert bar.close_ts.hour == 16
    assert t.hour == 16
    assert bar.close_ts >= t.astimezone(UTC)
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"
    assert label(ZONE, bar, t=t, htf_bias="box", closed_bars=closed) == "NOISE"


def test_exact_15pct_into_current_still_compresses() -> None:
    """|open − prev.close| / prev.close == 15% is not a gap — old ATR stays available."""
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("100"),
                high=Decimal("120"),
                low=Decimal("80"),
                close=Decimal("100"),
            )
        )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("115"),
        high=Decimal("115"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert abs(bar.open - closed[-1].close) / closed[-1].close == Decimal("0.15")
    assert (bar.high - bar.low) < Decimal("40")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"


def test_gap_into_current_does_not_borrow_old_atr() -> None:
    """15 priors at 130, current opens ~100: new segment has no closed bars → no COMPRESS."""
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("130"),
                high=Decimal("131"),
                low=Decimal("129"),
                close=Decimal("130"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert abs(bar.open - closed[-1].close) / closed[-1].close > Decimal("0.15")
    assert (bar.high - bar.low) < Decimal("2")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"


def _hist(i: int, *, close: str = "101", volume: Decimal | None = None) -> Bar:
    ts = datetime(2026, 8, 30, 12, 0, tzinfo=UTC).replace(minute=i)
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=ts,
        close_ts=ts.replace(second=30),
        open=Decimal(close),
        high=Decimal(close) + Decimal("1"),
        low=Decimal(close) - Decimal("1"),
        close=Decimal(close),
        volume=volume,
    )


def test_hourly_same_close_does_not_make_reject_noise() -> None:
    """4 same-symbol 1h closes equal to the reject close → stagnant NOISE if tf filter dropped."""
    hourly = []
    for i in range(4):
        ht = datetime(2026, 8, 29, 0, 0, tzinfo=UTC) + timedelta(hours=i)
        hourly.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ht,
                close_ts=ht + timedelta(hours=1),
                open=Decimal("100.1"),
                high=Decimal("101.1"),
                low=Decimal("99.1"),
                close=Decimal("100.1"),
            )
        )
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert sum(1 for b in hourly if b.close_ts < bar.close_ts) == 4
    assert prior_same_tf(hourly, bar, t=T) == []
    assert label(ZONE, bar, t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=hourly) == "REJECT"


def test_hourly_zero_volume_does_not_make_reject_noise() -> None:
    """1h zero-vol + reject zero-vol → illiquid NOISE if tf filter dropped."""
    ht = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    hourly = [
        Bar(
            symbol="BTCUSDT",
            tf="1h",
            open_ts=ht,
            close_ts=ht + timedelta(hours=1),
            open=Decimal("101"),
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("101"),
            volume=Decimal("0"),
        )
    ]
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert hourly[0].close_ts < bar.close_ts
    assert prior_same_tf(hourly, bar, t=T) == []
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=hourly) == "REJECT"


def test_stagnant_would_be_reject_is_noise() -> None:
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_stagnant_would_be_through_is_noise() -> None:
    """Quality is not only a REJECT gate. A dead through-bar is still NOISE."""
    closed = [_hist(i, close="99.8") for i in range(4)]
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_stagnant_would_be_compress_is_noise() -> None:
    """15 same-close ATR bars + a tight print is COMPRESS unless quality runs first."""
    closed = [_hist(i, close="100.10") for i in range(15)]
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "COMPRESS"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_four_same_closes_is_still_reject() -> None:
    closed = [_hist(i, close="100.1") for i in range(3)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "REJECT"


def test_illiquid_would_be_reject_is_noise() -> None:
    closed = [_hist(0, close="101", volume=Decimal("0"))]
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_illiquid_would_be_through_is_noise() -> None:
    closed = [_hist(0, close="101", volume=Decimal("0"))]
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("99.8"),
        high=Decimal("100.1"),
        low=Decimal("99.5"),
        close=Decimal("99.8"),
        volume=Decimal("0"),
    )
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_missing_volume_is_not_illiquid() -> None:
    closed = [_hist(0, close="101", volume=None)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert bar.volume is None
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "REJECT"


def test_gap_is_not_noise_reject_still_holds() -> None:
    closed = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
            close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
            open=Decimal("80"),
            high=Decimal("81"),
            low=Decimal("79"),
            close=Decimal("80"),
        )
    ]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert abs(bar.open - Decimal("80")) / Decimal("80") > Decimal("0.15")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "REJECT"


def test_short_post_gap_segment_is_not_compress() -> None:
    """3 bars after a jump, current continues that price — ATR window is short, not a gap-into-current."""
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="support",
        lo=Decimal("129.9"),
        hi=Decimal("130.1"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(12):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    for i in range(12, 15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("130"),
                high=Decimal("131"),
                low=Decimal("129"),
                close=Decimal("130"),
            )
        )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("130"),
        high=Decimal("130.05"),
        low=Decimal("129.95"),
        close=Decimal("130.00"),
    )
    assert abs(bar.open - closed[-1].close) / closed[-1].close == Decimal("0")
    assert label(zone, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    # Closes must not all equal current.close, or quality becomes stagnant → NOISE.
    long_seg = closed[:12] + [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=start.replace(minute=12 + i),
            close_ts=start.replace(minute=12 + i, second=30),
            open=Decimal("131"),
            high=Decimal("132"),
            low=Decimal("130"),
            close=Decimal("131"),
        )
        for i in range(15)
    ]
    assert abs(bar.open - long_seg[-1].close) / long_seg[-1].close < Decimal("0.15")
    assert label(zone, bar, t=T, htf_bias="box", closed_bars=long_seg) == "COMPRESS"


def test_stagnant_through_is_noise() -> None:
    closed = [_hist(i, close="99.8") for i in range(4)]
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_stagnant_resistance_reject_is_noise() -> None:
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.8", high="100.4", close="100.1")
    assert label(res, bar, t=T, htf_bias="box") == "REJECT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_foreign_symbol_and_tf_do_not_feed_atr() -> None:
    """ETH or 1h history that *would* COMPRESS if the filter dropped must stay DRIFT."""
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    eth = []
    hourly = []
    for i in range(15):
        ts = start.replace(minute=i)
        eth.append(
            Bar(
                symbol="ETHUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
        # Unique hours, all closed before the labeled 15m bar (16:30).
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
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert sum(1 for b in eth if b.close_ts < bar.close_ts) == 15
    assert sum(1 for b in hourly if b.close_ts < bar.close_ts) == 15
    assert prior_same_tf(eth, bar, t=T) == []
    assert prior_same_tf(hourly, bar, t=T) == []
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=eth) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=hourly) == "DRIFT"


def test_future_bar_does_not_create_compress() -> None:
    """14 priors → no ATR. A later bar before t must not complete the window."""
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(14):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    extra_prior = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 14, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 14, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    future = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 40, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("200"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [future]) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [extra_prior]) == "COMPRESS"


def test_unclosed_stagnant_history_is_noise_from_unclosed() -> None:
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.9", high="100.5", close="100.1", close_ts=T)
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_compress_survives_when_post_gap_segment_is_long() -> None:
    closed = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=datetime(2026, 8, 30, 11, 0, tzinfo=UTC),
            close_ts=datetime(2026, 8, 30, 11, 14, tzinfo=UTC),
            open=Decimal("80"),
            high=Decimal("81"),
            low=Decimal("79"),
            close=Decimal("80"),
        )
    ]
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"
