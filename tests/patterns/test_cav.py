"""CAV: closed bar only. Wick+close inside = REJECT. Close beyond = THROUGH."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from capitalizator.patterns.bar_quality import atr, last_gap_segment, prior_same_tf
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


def test_foreign_symbol_or_tf_bar_is_noise() -> None:
    """History isolation is not enough. An ETH or 1h reject-shape vs a BTC 15m zone is not REJECT."""
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    assert label(ZONE, _bar(low="99.9", high="100.5", close="100.1"), t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, eth, t=T, htf_bias="box") == "NOISE"
    assert label(ZONE, hourly, t=T, htf_bias="box") == "NOISE"


def test_matching_hourly_or_eth_zone_still_rejects() -> None:
    """Filter is bar vs zone, not a hardcoded 15m-BTC-only CAV."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    assert label(hourly_zone, hourly, t=T, htf_bias="box") == "REJECT"
    assert label(eth_zone, eth, t=T, htf_bias="box") == "REJECT"
    assert label(hourly_zone, eth, t=T, htf_bias="box") == "NOISE"


def test_close_beyond_support_is_through() -> None:
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"


def test_close_on_zone_lo_is_not_through() -> None:
    """THROUGH is close beyond the zone. `close <= lo` would fire on the edge."""
    bar = _bar(low="100.0", high="101.0", close="100")
    assert bar.close == ZONE.lo
    assert bar.low >= ZONE.lo
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"


def test_resistance_close_on_hi_is_not_through() -> None:
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    bar = _bar(low="100.0", high="100.2", close="100.2")
    assert bar.close == res.hi
    assert bar.high <= res.hi
    assert label(res, bar, t=T, htf_bias="box") == "DRIFT"


def test_htf_against_is_noise() -> None:
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="short") == "NOISE"


def test_htf_against_through_is_noise() -> None:
    """HTF is not only a REJECT gate. A through-bar against the bounce side is still NOISE."""
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="short") == "NOISE"


def test_htf_against_compress_is_noise() -> None:
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "COMPRESS"
    assert label(ZONE, bar, t=T, htf_bias="short", closed_bars=_atr15()) == "NOISE"


def test_htf_against_drift_is_noise() -> None:
    """HTF is not only REJECT/THROUGH/COMPRESS. A drift-bar against the bounce side is still NOISE."""
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="short") == "NOISE"


def test_htf_with_us_still_compresses() -> None:
    """Support bounce is long. `htf != box` would NOISE a same-side HTF."""
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="long", closed_bars=_atr15()) == "COMPRESS"


def test_htf_unknown_still_through() -> None:
    """unknown is not against. Dropping it from the allow-set would NOISE a real THROUGH."""
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="unknown") == "THROUGH"


def test_htf_unknown_still_reject() -> None:
    """unknown is not a THROUGH-only allow. Dropping it would NOISE a real REJECT."""
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="unknown") == "REJECT"


def test_htf_unknown_still_drift() -> None:
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="unknown") == "DRIFT"


def test_htf_unknown_still_compress() -> None:
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert label(ZONE, bar, t=T, htf_bias="unknown", closed_bars=_atr15()) == "COMPRESS"


def test_htf_with_us_still_through() -> None:
    bar = _bar(low="99.5", high="100.1", close="99.8")
    assert label(ZONE, bar, t=T, htf_bias="long") == "THROUGH"


def test_htf_with_us_still_reject() -> None:
    """with-us is not only THROUGH/COMPRESS. Support long must not NOISE a REJECT."""
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="long") == "REJECT"


def test_htf_with_us_still_drift() -> None:
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="long") == "DRIFT"


def test_resistance_htf_against_is_noise() -> None:
    """Resistance bounce is short. Hardcoding against==short would miss long."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    reject = _bar(low="99.8", high="100.4", close="100.1")
    through = _bar(low="100.1", high="100.4", close="100.3")
    tight = _bar(low="100.05", high="100.15", close="100.10")
    assert label(res, reject, t=T, htf_bias="box") == "REJECT"
    assert label(res, reject, t=T, htf_bias="long") == "NOISE"
    assert label(res, through, t=T, htf_bias="box") == "THROUGH"
    assert label(res, through, t=T, htf_bias="long") == "NOISE"
    assert label(res, tight, t=T, htf_bias="box", closed_bars=_atr15()) == "COMPRESS"
    assert label(res, tight, t=T, htf_bias="long", closed_bars=_atr15()) == "NOISE"
    assert label(res, tight, t=T, htf_bias="short", closed_bars=_atr15()) == "COMPRESS"
    assert label(res, reject, t=T, htf_bias="short") == "REJECT"
    assert label(res, through, t=T, htf_bias="short") == "THROUGH"
    assert label(res, reject, t=T, htf_bias="unknown") == "REJECT"
    assert label(res, through, t=T, htf_bias="unknown") == "THROUGH"
    assert label(res, tight, t=T, htf_bias="unknown", closed_bars=_atr15()) == "COMPRESS"
    drift = _bar(low="100.0", high="100.2", close="100.1")
    assert label(res, drift, t=T, htf_bias="box") == "DRIFT"
    assert label(res, drift, t=T, htf_bias="unknown") == "DRIFT"
    assert label(res, drift, t=T, htf_bias="short") == "DRIFT"


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


def test_fourteen_btc_and_one_eth_do_not_compress() -> None:
    """14 BTC + 1 ETH is 15 bars. Counting every symbol would COMPRESS (or atr() raise)."""
    closed = _atr15()[:14]
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 14, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 14, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert len(closed) == 14
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [eth]) == "DRIFT"


def test_fourteen_eth_and_one_btc_do_not_compress() -> None:
    """14 ETH + 1 BTC is 15 bars. Counting every symbol would COMPRESS an ETH zone."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(14):
        ts = start.replace(minute=i)
        closed.append(
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
    btc = _atr15()[14]
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert closed[-1].close_ts < btc.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [btc]) == "DRIFT"


def test_fourteen_hourly_and_one_15m_do_not_compress() -> None:
    """14 1h + 1 15m is 15 bars. Counting every tf would COMPRESS a 1h zone."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(14):
        ts = start + timedelta(hours=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ts,
                close_ts=ts + timedelta(hours=1),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    foreign = _hist(10)
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert closed[-1].close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [foreign]) == "DRIFT"


def test_fifteen_btc_still_compress_when_later_eth_looks_like_a_jump() -> None:
    """15 BTC + later ETH at 80. Mixed last-prior jumps into current and empties ATR → DRIFT."""
    closed = _atr15()
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert closed[-1].close_ts < eth.close_ts < bar.close_ts
    assert abs(bar.open - eth.close) / eth.close > Decimal("0.15")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [eth]) == "COMPRESS"


def test_fifteen_eth_still_compress_when_later_btc_looks_like_a_jump() -> None:
    """Hardcoded `history is BTC` keeps only the late BTC 80 — a jump that empties ATR."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
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
    btc = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert closed[-1].close_ts < btc.close_ts < eth.close_ts
    assert abs(eth.open - btc.close) / btc.close > Decimal("0.15")
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [btc]) == "COMPRESS"


def test_fifteen_hourly_still_compress_when_later_15m_looks_like_a_jump() -> None:
    """Hardcoded `tf==15m` keeps only the late 15m 80 — a jump that empties ATR."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(15):
        ts = start + timedelta(hours=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ts,
                close_ts=ts + timedelta(hours=1),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert closed[-1].close_ts < foreign.close_ts < hourly.close_ts
    assert abs(hourly.open - foreign.close) / foreign.close > Decimal("0.15")
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [foreign]) == "COMPRESS"


def test_fourteen_15m_and_one_1h_do_not_compress() -> None:
    """14 15m + 1h is 15 bars. Counting every tf would COMPRESS (or split_on_gaps raise)."""
    closed = _atr15()[:14]
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert hourly.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [hourly]) == "DRIFT"


def test_bar_closing_during_current_completes_compress() -> None:
    """A bar that closes after current.open and before current.close is a 15th ATR prior."""
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
    assert bar.open_ts < mid.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [mid]) == "COMPRESS"


def test_same_close_ts_twin_does_not_complete_atr() -> None:
    """A different object with the same close_ts is not a prior. `is current` would leak ATR."""
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
    twin = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=bar.open_ts,
        close_ts=bar.close_ts,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    assert twin.close_ts == bar.close_ts
    assert twin is not bar
    assert atr(closed + [twin]) == Decimal("2")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [twin]) == "DRIFT"


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


def test_tight_range_close_above_zone_is_not_compress() -> None:
    """COMPRESS needs close inside. A touch with range < ATR and close above the box is NOISE."""
    bar = _bar(low="100.15", high="100.25", close="100.22")
    assert bar.low <= ZONE.hi
    assert bar.high >= ZONE.lo
    assert bar.close > ZONE.hi
    assert (bar.high - bar.low) < Decimal("2")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "NOISE"


def test_tight_range_close_below_resistance_is_not_compress() -> None:
    """Resistance close under the box is not COMPRESS even when range < ATR and the wick still touches."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    bar = _bar(low="99.90", high="100.05", close="99.95")
    assert bar.low <= res.hi
    assert bar.high >= res.lo
    assert bar.close < res.lo
    assert (bar.high - bar.low) < Decimal("2")
    assert label(res, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "NOISE"


def test_range_equal_to_atr_is_drift_not_compress() -> None:
    """COMPRESS is range < ATR, not <=. Body is 0 here — |close−open| < ATR would fake COMPRESS."""
    bar = _bar(low="100.0", high="102.0", close="100.10")
    assert (bar.high - bar.low) == Decimal("2")
    assert abs(bar.close - bar.open) == Decimal("0")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "DRIFT"


def test_compress_uses_last_atr_window_not_the_first() -> None:
    """Range 3 sits between last-window ATR=2 and first-window 60/14. First 15 would COMPRESS."""
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    closed = []
    for i in range(5):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("100"),
                close=Decimal("100"),
            )
        )
    for i in range(5, 20):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("100"),
            )
        )
    bar = _bar(low="100.0", high="103.0", close="100.10")
    assert (bar.high - bar.low) == Decimal("3")
    assert len(last_gap_segment(closed, bar, t=T)) == 20
    assert atr(closed[:15]) == Decimal("60") / Decimal("14")
    assert (bar.high - bar.low) < atr(closed[:15])
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"


def test_compress_uses_mean_true_range_not_median() -> None:
    """Range 2.2 < mean TR 40/14 and > median TR 2. Median ATR would be DRIFT."""
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    closed = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=start,
            close_ts=start.replace(second=30),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
    ]
    ts = start.replace(minute=1)
    closed.append(
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=ts,
            close_ts=ts.replace(second=30),
            open=Decimal("114"),
            high=Decimal("114"),
            low=Decimal("113"),
            close=Decimal("114"),
        )
    )
    for i in range(2, 15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("114"),
                high=Decimal("116"),
                low=Decimal("114"),
                close=Decimal("114"),
            )
        )
    bar = _bar(low="100.0", high="102.2", close="100.10")
    assert (bar.high - bar.low) == Decimal("2.2")
    assert abs(bar.open - closed[-1].close) / closed[-1].close < Decimal("0.15")
    assert atr(closed) == Decimal("40") / Decimal("14")
    assert (bar.high - bar.low) < atr(closed)
    assert (bar.high - bar.low) > Decimal("2")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "COMPRESS"


def test_plus530_t_does_not_close_a_1300z_bar() -> None:
    """+3 16:45 is 13:45Z — bar is closed. +5:30 16:45 is 11:15Z. Hardcoded -3 would COMPRESS."""
    plus3 = timezone(timedelta(hours=3))
    plus530 = timezone(timedelta(hours=5, minutes=30))
    t3 = datetime(2026, 8, 30, 16, 45, tzinfo=plus3)
    t530 = datetime(2026, 8, 30, 16, 45, tzinfo=plus530)
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 45, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert t3.astimezone(UTC) == datetime(2026, 8, 30, 13, 45, tzinfo=UTC)
    assert t530.astimezone(UTC) == datetime(2026, 8, 30, 11, 15, tzinfo=UTC)
    assert label(ZONE, bar, t=t3, htf_bias="box", closed_bars=_atr15()) == "COMPRESS"
    assert label(ZONE, bar, t=t530, htf_bias="box", closed_bars=_atr15()) == "NOISE"


def test_plus9_close_ts_compresses_at_utc_noon() -> None:
    """+9 16:30 close is 07:30Z. Clock 16:30 > 12:00 would NOISE a bar that already closed."""
    plus9 = timezone(timedelta(hours=9))
    t = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    start = datetime(2026, 8, 30, 3, 30, tzinfo=UTC)
    closed = []
    for i in range(15):
        ts = start + timedelta(minutes=15 * i)
        closed.append(
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
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=plus9),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=plus9),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert bar.close_ts.hour == 16
    assert t.hour == 12
    assert bar.close_ts < t
    assert closed[-1].close_ts < bar.close_ts
    assert label(ZONE, bar, t=t, htf_bias="box", closed_bars=closed) == "COMPRESS"


def test_plus9_prior_completes_compress() -> None:
    """+9 16:30 prior is 07:30Z. Clock 16:30 > 08:00 current would leave 14 bars and DRIFT."""
    plus9 = timezone(timedelta(hours=9))
    t = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    start = datetime(2026, 8, 30, 3, 45, tzinfo=UTC)
    closed = []
    for i in range(14):
        ts = start + timedelta(minutes=15 * i)
        closed.append(
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
    off = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=plus9),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=plus9),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 7, 45, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert off.close_ts.hour == 16
    assert bar.close_ts.hour == 8
    assert off.close_ts < bar.close_ts
    assert len(prior_same_tf(closed, bar, t=t)) == 14
    assert len(prior_same_tf(closed + [off], bar, t=t)) == 15
    assert label(ZONE, bar, t=t, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=t, htf_bias="box", closed_bars=closed + [off]) == "COMPRESS"


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


def test_eth_gap_stays_drift_when_later_btc_hides_the_jump() -> None:
    """15 ETH at 130 + later BTC at current open. Counting every symbol would COMPRESS."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
            Bar(
                symbol="ETHUSDT",
                tf="15m",
                open_ts=ts,
                close_ts=ts.replace(second=30),
                open=Decimal("130"),
                high=Decimal("131"),
                low=Decimal("129"),
                close=Decimal("130"),
            )
        )
    btc = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert closed[-1].close_ts < btc.close_ts < eth.close_ts
    assert abs(eth.open - closed[-1].close) / closed[-1].close > Decimal("0.15")
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [btc]) == "DRIFT"


def test_gap_into_current_stays_drift_when_later_eth_hides_the_jump() -> None:
    """15 BTC at 130 + later ETH at current open. Mixed last-prior has no jump → COMPRESS."""
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
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert closed[-1].close_ts < eth.close_ts < bar.close_ts
    assert abs(bar.open - closed[-1].close) / closed[-1].close > Decimal("0.15")
    assert abs(bar.open - eth.close) / eth.close < Decimal("0.15")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [eth]) == "DRIFT"


def test_hourly_gap_stays_drift_when_later_15m_hides_the_jump() -> None:
    """15 1h at 130 + later 15m at current open. Mixed last-prior has no jump → COMPRESS."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(15):
        ts = start + timedelta(hours=i)
        closed.append(
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
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert closed[-1].close_ts < foreign.close_ts < hourly.close_ts
    assert abs(hourly.open - closed[-1].close) / closed[-1].close > Decimal("0.15")
    assert abs(hourly.open - foreign.close) / foreign.close < Decimal("0.15")
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed) == "DRIFT"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [foreign]) == "DRIFT"


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


def test_reject_does_not_go_noise_when_none_volume_neighbor_plus_eth_zero() -> None:
    """Same-tf neighbor volume=None is not a zero. Mixed last-2 is ETH 0 + reject 0 → NOISE."""
    neighbor = _hist(0, volume=None)
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
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
    assert neighbor.volume is None
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "REJECT"


def test_reject_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """15m BTC vol=1 + 15m ETH vol=0 + reject vol=0. Mixed last-2 is ILLIQUID → NOISE."""
    neighbor = _hist(0, volume=Decimal("1"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
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
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "REJECT"


def test_reject_does_not_go_noise_when_last_two_would_be_illiquid_only_via_1h_zero() -> None:
    """15m vol=1 + 1h vol=0 closing after it + reject vol=0. Mixed last-2 is ILLIQUID → NOISE."""
    neighbor = _hist(0, volume=Decimal("1"))
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
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
    assert neighbor.close_ts < hourly.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, hourly]) == "REJECT"


def test_eth_reject_does_not_go_noise_when_last_two_would_be_illiquid_only_via_btc_zero() -> None:
    """Hardcoded `history is BTC` takes BTC vol=0 + ETH reject vol=0 as last-2 → NOISE."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = _hist(10, volume=Decimal("0"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "REJECT"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "REJECT"


def test_hourly_reject_does_not_go_noise_when_last_two_would_be_illiquid_only_via_15m_zero() -> None:
    """Hardcoded `tf==15m` takes 15m vol=0 + 1h reject vol=0 as last-2 → NOISE."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "REJECT"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "REJECT"


def test_reject_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """BTC vol=0 + ETH vol=1 + reject vol=0. Mixed last-2 is LIVE. Same-series last-2 is ILLIQUID."""
    neighbor = _hist(0, volume=Decimal("0"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
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
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_eth_reject_stays_noise_when_btc_volume_sits_between_two_zeros() -> None:
    """Hardcoded `history is BTC` takes BTC vol=1 + ETH reject vol=0 as last-2 → REJECT."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = _hist(10, volume=Decimal("1"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_hourly_reject_stays_noise_when_15m_volume_sits_between_two_zeros() -> None:
    """Hardcoded `tf==15m` takes 15m vol=1 + 1h reject vol=0 as last-2 → REJECT."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_15m_zero_volume_does_not_noise_a_1h_reject() -> None:
    """Hardcoded `tf==15m` would ILLIQUID a 1h reject. Filter is current.tf."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[_hist(0, volume=Decimal("0"))]) == "REJECT"


def test_btc_zero_volume_does_not_noise_an_eth_reject() -> None:
    """Hardcoded `history is BTC` would ILLIQUID an ETH reject. Filter is current.symbol."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[_hist(0, volume=Decimal("0"))]) == "REJECT"


def test_stagnant_would_be_reject_is_noise() -> None:
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_stagnant_with_us_htf_is_still_noise() -> None:
    """HTF with-us is not a quality bypass. Stagnant reject-shape + long is still NOISE."""
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="long") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="long", closed_bars=closed) == "NOISE"


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


def test_broken_last_five_is_still_reject() -> None:
    """Five 100.1 closes exist in the series, but the last five are broken — not NOISE."""
    closed = [_hist(i, close="100.1") for i in range(4)] + [_hist(4, close="101")]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    assert sum(1 for b in closed + [bar] if b.close == Decimal("100.1")) == 5
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "REJECT"


def test_unsorted_broken_last_five_is_still_reject() -> None:
    """Late 101 first in the list: last-five without a sort are five 100.1s → false NOISE."""
    late = _hist(4, close="101")
    early = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="99.9", high="100.5", close="100.1")
    closed = [late] + early
    assert closed[0].close == Decimal("101")
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


def test_illiquid_with_us_htf_is_still_noise() -> None:
    """HTF with-us is not an illiquid bypass. Zero-vol reject-shape + long is still NOISE."""
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
    assert label(ZONE, bar, t=T, htf_bias="long") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="long", closed_bars=closed) == "NOISE"


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


def test_through_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """15m BTC vol=1 + 15m ETH vol=0 + through vol=0. Mixed last-2 is ILLIQUID → NOISE."""
    neighbor = _hist(0, volume=Decimal("1"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
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
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "THROUGH"


def test_through_does_not_go_noise_when_last_two_would_be_illiquid_only_via_1h_zero() -> None:
    """15m vol=1 + 1h vol=0 closing after it + through vol=0. Mixed last-2 is ILLIQUID → NOISE."""
    neighbor = _hist(0, volume=Decimal("1"))
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
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
    assert neighbor.close_ts < hourly.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, hourly]) == "THROUGH"


def test_through_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """BTC vol=0 + ETH vol=1 + through vol=0. Mixed last-2 is LIVE → THROUGH."""
    neighbor = _hist(0, volume=Decimal("0"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
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
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_resistance_through_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance through is ILLIQUID → NOISE."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = _hist(0, volume=Decimal("1"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.3"),
        high=Decimal("100.4"),
        low=Decimal("100.1"),
        close=Decimal("100.3"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "THROUGH"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "THROUGH"


def test_resistance_through_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance through is LIVE → THROUGH."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = _hist(0, volume=Decimal("0"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.3"),
        high=Decimal("100.4"),
        low=Decimal("100.1"),
        close=Decimal("100.3"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box") == "THROUGH"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_resistance_compress_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance compress is ILLIQUID → NOISE."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    closed = _atr15()
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "COMPRESS"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "COMPRESS"


def test_resistance_compress_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance compress is LIVE → COMPRESS."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    closed = _atr15()
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "NOISE"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "NOISE"


def test_resistance_reject_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance reject is LIVE → REJECT."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = _hist(0, volume=Decimal("0"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.4"),
        low=Decimal("99.8"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box") == "REJECT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_eth_through_does_not_go_noise_when_last_two_would_be_illiquid_only_via_btc_zero() -> None:
    """Hardcoded `history is BTC` takes BTC vol=0 + ETH through vol=0 as last-2 → NOISE."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = _hist(10, volume=Decimal("0"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("99.8"),
        high=Decimal("100.1"),
        low=Decimal("99.5"),
        close=Decimal("99.8"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box") == "THROUGH"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "THROUGH"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "THROUGH"


def test_eth_through_stays_noise_when_btc_volume_sits_between_two_zeros() -> None:
    """Hardcoded `history is BTC` takes BTC vol=1 + ETH through vol=0 as last-2 → THROUGH."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = _hist(10, volume=Decimal("1"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("99.8"),
        high=Decimal("100.1"),
        low=Decimal("99.5"),
        close=Decimal("99.8"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box") == "THROUGH"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_hourly_through_does_not_go_noise_when_last_two_would_be_illiquid_only_via_15m_zero() -> None:
    """Hardcoded `tf==15m` takes 15m vol=0 + 1h through vol=0 as last-2 → NOISE."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("99.8"),
        high=Decimal("100.1"),
        low=Decimal("99.5"),
        close=Decimal("99.8"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box") == "THROUGH"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "THROUGH"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "THROUGH"


def test_hourly_through_stays_noise_when_15m_volume_sits_between_two_zeros() -> None:
    """Hardcoded `tf==15m` takes 15m vol=1 + 1h through vol=0 as last-2 → THROUGH."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("99.8"),
        high=Decimal("100.1"),
        low=Decimal("99.5"),
        close=Decimal("99.8"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box") == "THROUGH"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_compress_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """15 ATR + vol=1 + ETH vol=0 + tight vol=0. Mixed last-2 is ILLIQUID → NOISE."""
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    closed = _atr15()
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "COMPRESS"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "COMPRESS"


def test_compress_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """15 ATR + vol=0 + ETH vol=1 + tight vol=0. Mixed last-2 is LIVE → COMPRESS."""
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    closed = _atr15()
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "NOISE"


def test_eth_compress_does_not_go_noise_when_last_two_would_be_illiquid_only_via_btc_zero() -> None:
    """Hardcoded `history is BTC` takes BTC vol=0 + ETH tight vol=0 as last-2 → NOISE."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
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
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "COMPRESS"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "COMPRESS"


def test_eth_compress_stays_noise_when_btc_volume_sits_between_two_zeros() -> None:
    """Hardcoded `history is BTC` takes BTC vol=1 + ETH tight vol=0 as last-2 → COMPRESS."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    for i in range(15):
        ts = start.replace(minute=i)
        closed.append(
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
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "NOISE"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "NOISE"


def test_hourly_compress_does_not_go_noise_when_last_two_would_be_illiquid_only_via_15m_zero() -> None:
    """Hardcoded `tf==15m` takes 15m vol=0 + 1h tight vol=0 as last-2 → NOISE."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(15):
        ts = start + timedelta(hours=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ts,
                close_ts=ts + timedelta(hours=1),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "COMPRESS"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "COMPRESS"


def test_hourly_compress_stays_noise_when_15m_volume_sits_between_two_zeros() -> None:
    """Hardcoded `tf==15m` takes 15m vol=1 + 1h tight vol=0 as last-2 → COMPRESS."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    closed = []
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    for i in range(15):
        ts = start + timedelta(hours=i)
        closed.append(
            Bar(
                symbol="BTCUSDT",
                tf="1h",
                open_ts=ts,
                close_ts=ts + timedelta(hours=1),
                open=Decimal("101"),
                high=Decimal("102"),
                low=Decimal("100"),
                close=Decimal("101"),
            )
        )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [neighbor]) == "NOISE"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=closed + [neighbor, foreign]) == "NOISE"


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


def test_btc_history_does_not_compress_an_eth_zone() -> None:
    """Hardcoded `history is BTC` would COMPRESS an ETH zone. Filter is current.symbol, not a fixed ticker."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=_atr15()) == "DRIFT"


def test_15m_history_does_not_compress_a_1h_zone() -> None:
    """Hardcoded `tf==15m` would COMPRESS a 1h zone. Filter is current.tf, not a fixed working TF."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.10"),
        high=Decimal("100.15"),
        low=Decimal("100.05"),
        close=Decimal("100.10"),
    )
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=_atr15()) == "DRIFT"


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


def test_stagnant_would_be_drift_is_noise() -> None:
    """Quality is not only REJECT/THROUGH/COMPRESS. A dead drift-bar is still NOISE."""
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_illiquid_would_be_drift_is_noise() -> None:
    closed = [_hist(0, close="101", volume=Decimal("0"))]
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=closed) == "NOISE"


def test_resistance_htf_against_drift_is_noise() -> None:
    """HTF is not only REJECT/THROUGH/COMPRESS on resistance. Drift against the bounce is NOISE."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    bar = _bar(low="100.0", high="100.2", close="100.1")
    assert label(res, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(res, bar, t=T, htf_bias="long") == "NOISE"
    assert label(res, bar, t=T, htf_bias="short") == "DRIFT"


def test_drift_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """15m BTC vol=1 + 15m ETH vol=0 + drift vol=0. Mixed last-2 is ILLIQUID → NOISE."""
    neighbor = _hist(0, volume=Decimal("1"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "DRIFT"


def test_drift_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """BTC vol=0 + ETH vol=1 + drift vol=0. Mixed last-2 is LIVE → DRIFT."""
    neighbor = _hist(0, volume=Decimal("0"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_resistance_drift_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance drift is ILLIQUID → NOISE."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = _hist(0, volume=Decimal("1"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.2"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "DRIFT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "DRIFT"


def test_resistance_drift_stays_noise_when_foreign_volume_sits_between_two_zeros() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance drift is LIVE → DRIFT."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = _hist(0, volume=Decimal("0"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.2"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_eth_drift_does_not_go_noise_when_last_two_would_be_illiquid_only_via_btc_zero() -> None:
    """Hardcoded `history is BTC` takes BTC vol=0 + ETH drift vol=0 as last-2 → NOISE."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = _hist(10, volume=Decimal("0"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box") == "DRIFT"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "DRIFT"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "DRIFT"


def test_eth_drift_stays_noise_when_btc_volume_sits_between_two_zeros() -> None:
    """Hardcoded `history is BTC` takes BTC vol=1 + ETH drift vol=0 as last-2 → DRIFT."""
    eth_zone = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = _hist(10, volume=Decimal("1"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(eth_zone, eth, t=T, htf_bias="box") == "DRIFT"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(eth_zone, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_hourly_drift_does_not_go_noise_when_last_two_would_be_illiquid_only_via_15m_zero() -> None:
    """Hardcoded `tf==15m` takes 15m vol=0 + 1h drift vol=0 as last-2 → NOISE."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box") == "DRIFT"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "DRIFT"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "DRIFT"


def test_hourly_drift_stays_noise_when_15m_volume_sits_between_two_zeros() -> None:
    """Hardcoded `tf==15m` takes 15m vol=1 + 1h drift vol=0 as last-2 → DRIFT."""
    hourly_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(hourly_zone, hourly, t=T, htf_bias="box") == "DRIFT"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(hourly_zone, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_resistance_reject_does_not_go_noise_when_last_two_would_be_illiquid_only_via_eth_zero() -> None:
    """Quality is not a support-only gate. Mixed last-2 on resistance reject is ILLIQUID → NOISE."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = _hist(0, volume=Decimal("1"))
    foreign = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 14, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.4"),
        low=Decimal("99.8"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < bar.close_ts
    assert label(res, bar, t=T, htf_bias="box") == "REJECT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor]) == "REJECT"
    assert label(res, bar, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "REJECT"


def test_stagnant_drift_with_us_htf_is_still_noise() -> None:
    """HTF with-us is not a quality bypass. Stagnant drift-shape + long is still NOISE."""
    closed = [_hist(i, close="100.1") for i in range(4)]
    bar = _bar(low="100.0", high="101.0", close="100.1")
    assert label(ZONE, bar, t=T, htf_bias="long") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="long", closed_bars=closed) == "NOISE"


def test_eth_resistance_drift_does_not_go_noise_when_last_two_would_be_illiquid_only_via_btc_zero() -> None:
    """BTC-only or support-only quality would ILLIQUID ETH resistance drift via BTC vol=0."""
    res = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = _hist(10, volume=Decimal("0"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.2"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(res, eth, t=T, htf_bias="box") == "DRIFT"
    assert label(res, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "DRIFT"
    assert label(res, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "DRIFT"


def test_eth_resistance_drift_stays_noise_when_btc_volume_sits_between_two_zeros() -> None:
    """BTC-only or support-only quality would take BTC vol=1 + ETH drift vol=0 as last-2 → DRIFT."""
    res = Zone.create(
        symbol="ETHUSDT",
        tf="15m",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 12, 0, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = _hist(10, volume=Decimal("1"))
    eth = Bar(
        symbol="ETHUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.2"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < eth.close_ts
    assert label(res, eth, t=T, htf_bias="box") == "DRIFT"
    assert label(res, eth, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(res, eth, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_hourly_resistance_drift_does_not_go_noise_when_last_two_would_be_illiquid_only_via_15m_zero() -> None:
    """15m-only or support-only quality would ILLIQUID 1h resistance drift via 15m vol=0."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.2"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(res, hourly, t=T, htf_bias="box") == "DRIFT"
    assert label(res, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "DRIFT"
    assert label(res, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "DRIFT"


def test_hourly_resistance_drift_stays_noise_when_15m_volume_sits_between_two_zeros() -> None:
    """15m-only or support-only quality would take 15m vol=1 + 1h drift vol=0 as last-2 → DRIFT."""
    res = Zone.create(
        symbol="BTCUSDT",
        tf="1h",
        side="resistance",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="swing",
        created_as_of=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )
    neighbor = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    foreign = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.2"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert neighbor.close_ts < foreign.close_ts < hourly.close_ts
    assert label(res, hourly, t=T, htf_bias="box") == "DRIFT"
    assert label(res, hourly, t=T, htf_bias="box", closed_bars=[neighbor]) == "NOISE"
    assert label(res, hourly, t=T, htf_bias="box", closed_bars=[neighbor, foreign]) == "NOISE"


def test_reject_goes_noise_when_last_two_are_illiquid_via_mid_bar_zero() -> None:
    """A zero that closes during current is the last-2 neighbor. `< open_ts` would keep REJECT."""
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
    assert bar.open_ts < mid.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[mid]) == "NOISE"


def test_reject_does_not_go_noise_when_mid_bar_volume_sits_between_two_zeros() -> None:
    """Earlier zero + mid vol=1 during current + reject vol=0. Dropping mid makes last-2 ILLIQUID."""
    early = _hist(0, volume=Decimal("0"))
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
    assert early.close_ts < mid.close_ts < bar.close_ts
    assert bar.open_ts < mid.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[early]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[early, mid]) == "REJECT"


def test_drift_goes_noise_when_last_two_are_illiquid_via_mid_bar_zero() -> None:
    """Quality is not only REJECT. Mid-bar zero + drift zero is last-2 ILLIQUID → NOISE."""
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
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert bar.open_ts < mid.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[mid]) == "NOISE"


def test_drift_does_not_go_noise_when_mid_bar_volume_sits_between_two_zeros() -> None:
    """Earlier zero + mid vol=1 during current + drift vol=0. Dropping mid makes last-2 ILLIQUID."""
    early = _hist(0, volume=Decimal("0"))
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
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.0"),
        low=Decimal("100.0"),
        close=Decimal("100.1"),
        volume=Decimal("0"),
    )
    assert early.close_ts < mid.close_ts < bar.close_ts
    assert bar.open_ts < mid.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "DRIFT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[early]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[early, mid]) == "DRIFT"


def test_compress_stays_drift_when_mid_bar_hides_a_real_jump() -> None:
    """15 at 101 + mid at 80 during current. `< open_ts` would borrow old ATR → COMPRESS."""
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
    bar = _bar(low="100.05", high="100.15", close="100.10")
    assert bar.open_ts < mid.close_ts < bar.close_ts
    assert abs(bar.open - Decimal("101")) / Decimal("101") < Decimal("0.15")
    assert abs(bar.open - mid.close) / mid.close > Decimal("0.15")
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15()) == "COMPRESS"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=_atr15() + [mid]) == "DRIFT"


def test_reject_does_not_go_noise_when_equal_close_ts_last_two_need_open_tiebreak() -> None:
    """Same close_ts [vol1, vol0] + reject vol=0. Close-only last-2 is two zeros → NOISE."""
    close = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)
    early_zero = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
    late_vol = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
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
    assert early_zero.close_ts == late_vol.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[late_vol, early_zero]) == "REJECT"


def test_reject_stays_noise_when_equal_close_ts_later_open_is_the_zero() -> None:
    """Later-open zero is the neighbor. Close-only [zero, vol1] would take early vol=1 → REJECT."""
    close = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)
    early_vol = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )
    late_zero = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 50, tzinfo=UTC),
        close_ts=close,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=Decimal("0"),
    )
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
    assert early_vol.close_ts == late_zero.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[late_zero, early_vol]) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[early_vol, late_zero]) == "NOISE"


def test_reject_does_not_go_noise_when_later_close_has_volume() -> None:
    """Later close is later even if it opened first. Open-order last-2 is short zero + reject zero."""
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
    assert short_zero.open_ts > long_vol.open_ts
    assert short_zero.close_ts < long_vol.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[long_vol, short_zero]) == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=[short_zero, long_vol]) == "REJECT"


def test_reject_goes_noise_when_stagnant_last_five_order_by_close_not_open() -> None:
    """101 closes before a long 100.1. Open-order last-5 still sees 101 → false REJECT."""
    p0 = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 15, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.1"),
        low=Decimal("99.1"),
        close=Decimal("100.1"),
    )
    short_break = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 15, 20, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    later = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=datetime(2026, 8, 30, 15, 45, tzinfo=UTC) + timedelta(minutes=15 * i),
            close_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC) + timedelta(minutes=15 * i),
            open=Decimal("100.1"),
            high=Decimal("101.1"),
            low=Decimal("99.1"),
            close=Decimal("100.1"),
        )
        for i in range(2)
    ]
    tail = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 8, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.1"),
        low=Decimal("99.1"),
        close=Decimal("100.1"),
    )
    long_same = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 14, 45, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 12, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("101.1"),
        low=Decimal("99.1"),
        close=Decimal("100.1"),
    )
    bar = _bar(low="99.9", high="100.5", close="100.1")
    hist = [p0, short_break, *later, tail, long_same]
    assert short_break.open_ts > long_same.open_ts
    assert short_break.close_ts < later[0].close_ts < tail.close_ts < long_same.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box") == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=hist) == "NOISE"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=list(reversed(hist))) == "NOISE"


def test_reject_stays_reject_when_breaking_close_is_last_despite_early_open() -> None:
    """101 closes last on the early-open long bar. Open-order last-5 drops it → false NOISE."""
    later = [_hist(i, close="100.1") for i in (10, 11, 12, 13)]
    long_break = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 30, 11, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 10, tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
    )
    bar = _bar(low="99.9", high="100.5", close="100.1")
    hist = [*later, long_break]
    assert long_break.open_ts < later[0].open_ts
    assert later[-1].close_ts < long_break.close_ts < bar.close_ts
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=hist) == "REJECT"
    assert label(ZONE, bar, t=T, htf_bias="box", closed_bars=list(reversed(hist))) == "REJECT"
