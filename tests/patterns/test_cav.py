"""CAV: closed bar only. Wick+close inside = REJECT. Close beyond = THROUGH."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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


def test_unclosed_bar_is_noise() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1", close_ts=T)
    assert label(ZONE, bar, t=T, htf_bias="box") == "NOISE"


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


def test_small_range_inside_zone_is_compress() -> None:
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
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"


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


def test_stagnant_would_be_reject_is_noise() -> None:
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
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


def test_gap_resets_atr_so_compress_needs_new_segment() -> None:
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
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"


def test_later_closed_bar_does_not_feed_atr() -> None:
    """PIT: a bar that closes after the labeled bar cannot widen ATR."""
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
    assert bar.close_ts < future.close_ts < T
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [future]) == "DRIFT"


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
