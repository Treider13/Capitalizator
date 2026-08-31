"""Width journal: PIT rank, gap segment, n<20 → None. Not size."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.patterns.width import (
    WidthSample,
    width_now,
    width_now_from_history,
    width_rank,
)
from capitalizator.zones.model import Bar

T0 = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)


def _bar(i: int, *, high: str = "102", low: str = "100", open_: str = "101", close: str = "101") -> Bar:
    ts = T0 + timedelta(minutes=15 * i)
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=ts,
        close_ts=ts + timedelta(minutes=15),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
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
    gapped = [_bar(0, open_="80", close="80", high="81", low="79")] + [
        _bar(i + 1, open_="101", close="101") for i in range(3)
    ]
    assert width_now_from_history(bar, gapped, t=NOW) is None


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


def test_naive_now_is_rejected() -> None:
    hist = [_sample(i, "1") for i in range(20)]
    with pytest.raises(TypeError, match="naive"):
        width_rank(zone_id="z1", now=datetime(2026, 8, 30, 18, 0), w_now=Decimal("2"), history=hist)


def test_sample_at_now_is_not_a_prior() -> None:
    hist = [_sample(i, "1") for i in range(19)]
    hist.append(WidthSample(zone_id="z1", ts=NOW, w_now=Decimal("1")))
    assert width_rank(zone_id="z1", now=NOW, w_now=Decimal("2"), history=hist) is None


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
    assert width_now_from_history(bar, hist, t=NOW) is None
