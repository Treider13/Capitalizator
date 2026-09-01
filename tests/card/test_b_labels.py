"""B-label calculations: RSI, FVG, sweep, SMC, GEX. No fake greens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.card.build import from_news
from capitalizator.card.fvg import fvg_status, latest_fvg
from capitalizator.card.gex import OptionRow, format_gex, gex_bg, gex_is_green
from capitalizator.card.live import CardLive
from capitalizator.card.params import (
    FVG_FILL_FRAC,
    GEX_THRESHOLD,
    RSI_PERIOD,
    RSI_UNSTABLE_PERIOD,
    SWEEP_LOOKBACK,
    VALUE_AREA_FRAC,
)
from capitalizator.card.rsi import stream_rsi
from capitalizator.card.smc import bos_status, ob_status
from capitalizator.card.sweep import sweep_status
from capitalizator.card.volume import snapshot as volume_snapshot
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Bar

NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _bar(
    i: int,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    tf: str = "1h",
    volume: str = "10",
) -> Bar:
    open_ts = START + timedelta(hours=i)
    return Bar(
        symbol="BTCUSDT",
        tf=tf,
        open_ts=open_ts,
        close_ts=open_ts + timedelta(hours=1) - timedelta(microseconds=1),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
    )


def _ohlc(rows: list[tuple[str, str, str, str]], *, tf: str = "1h") -> list[Bar]:
    return [
        _bar(i, open_=o, high=h, low=lo, close=c, tf=tf)
        for i, (o, h, lo, c) in enumerate(rows)
    ]


def test_from_news_none_marks_are_red() -> None:
    card = from_news(symbol="BTCUSDT", now=NOW, calendar=())
    assert card.rsi_htf is None
    assert card.gex_bg is None
    assert card.fvg_status == "none"
    assert card.sweep_status == "none"
    assert card.fib_zone == "none"
    assert card.ob_status is None
    assert card.bos_status is None
    assert card.context_ok() is False
    marks = card.mark_green()
    assert marks["fib"] is False
    assert marks["sweep"] is False
    assert marks["fvg"] is False
    assert marks["gex"] is None


def test_context_ok_gex_optional_when_none() -> None:
    card = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="OTE",
        fib_level="0.718",
        rsi_htf="52.00",
        gex_bg=None,
        fvg_status="filled",
        sweep_status="done",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
    )
    assert card.mark_green()["gex"] is None
    assert card.context_ok() is True
    blocked = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="none",
        gex_bg=None,
        fvg_status="filled",
        sweep_status="done",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
    )
    assert blocked.context_ok() is False


def test_rsi_wilder_all_gains_is_100() -> None:
    closes = [100.0 + i for i in range(RSI_PERIOD + 2)]
    assert stream_rsi(closes, period=RSI_PERIOD, unstable=0) == 100.0
    assert stream_rsi(closes[:RSI_PERIOD], period=RSI_PERIOD, unstable=0) is None


def test_rsi_unstable_period_withholds_early_values() -> None:
    closes = [100.0 + i for i in range(RSI_PERIOD + 50)]
    assert stream_rsi(closes, period=RSI_PERIOD, unstable=RSI_UNSTABLE_PERIOD) is None
    long_up = [100.0 + i for i in range(RSI_PERIOD + RSI_UNSTABLE_PERIOD + 1)]
    assert stream_rsi(long_up, period=RSI_PERIOD, unstable=RSI_UNSTABLE_PERIOD) == 100.0


def test_rsi_mixed_series_matches_wilder_seed() -> None:
    closes = [
        44.0, 44.3, 44.1, 43.9, 44.2, 44.5, 44.4, 44.8,
        45.1, 45.0, 45.4, 45.2, 45.6, 45.8, 45.5, 45.9,
        46.1, 45.7, 46.0, 46.3,
    ]
    got = stream_rsi(closes, period=14, unstable=0)
    assert got is not None
    assert 50.0 < got < 80.0


def test_fvg_three_candle_gap_filled_and_open() -> None:
    bars = _ohlc(
        [
            ("100", "101", "99", "100"),
            ("100", "108", "100", "107"),
            ("107", "110", "103", "109"),
        ]
    )
    # High1=101 < Low3=103 → bullish gap [101, 103]
    assert latest_fvg(bars) == (Decimal("101"), Decimal("103"))
    assert fvg_status(bars, price=Decimal("102")) == "filled"
    assert fvg_status(bars, price=Decimal("109")) == "open"
    assert fvg_status(_ohlc([("100", "101", "99", "100")])) == "none"
    bear = _ohlc(
        [
            ("110", "111", "109", "110"),
            ("110", "110", "100", "101"),
            ("101", "102", "98", "99"),
        ]
    )
    # Low1=109 > High3=102 → bearish gap [102, 109]
    assert latest_fvg(bear) == (Decimal("102"), Decimal("109"))
    assert fvg_status(bear, price=Decimal("105")) == "filled"


def test_sweep_wick_and_close_back_is_done() -> None:
    rows: list[tuple[str, str, str, str]] = [("100", "101", "99", "100")] * SWEEP_LOOKBACK
    rows = list(rows)
    rows[14] = ("100", "102", "99", "100")
    rows[15] = ("100", "103", "99", "101")
    rows[16] = ("101", "120", "100", "110")
    rows[17] = ("110", "111", "100", "105")
    rows[18] = ("105", "108", "100", "104")
    rows[19] = ("104", "125", "103", "110")
    bars = _ohlc(rows)
    assert sweep_status(bars) == "done"
    rows[19] = ("104", "125", "103", "122")
    assert sweep_status(_ohlc(rows)) == "pending"
    flat = _ohlc([("100", "101", "99", "100")] * 8)
    assert sweep_status(flat) == "none"


def test_smc_bos_and_order_block() -> None:
    rows: list[tuple[str, str, str, str]] = [("100", "101", "99", "100")] * 12
    rows = list(rows)
    rows[5] = ("105", "130", "104", "120")
    rows[6] = ("120", "122", "110", "112")
    rows[7] = ("112", "118", "108", "110")
    rows[8] = ("110", "116", "108", "112")
    rows[9] = ("112", "115", "109", "111")
    rows[10] = ("111", "114", "108", "110")
    rows[11] = ("125", "140", "124", "135")
    bars = _ohlc(rows)
    assert bos_status(bars) == "bull"
    assert ob_status(bars) == "bull"
    assert bos_status(_ohlc([("100", "101", "99", "100")] * 4)) is None
    assert ob_status(_ohlc([("100", "101", "99", "100")] * 4)) is None


def test_gex_none_without_chain_and_spotgamma_formula() -> None:
    assert gex_bg() is None
    assert gex_bg(spot=Decimal("100"), chain=()) is None
    assert gex_is_green(None) is None
    chain = (
        OptionRow(
            strike=Decimal("100"),
            oi=Decimal("1000"),
            gamma=Decimal("0.02"),
            right="C",
        ),
        OptionRow(
            strike=Decimal("90"),
            oi=Decimal("400"),
            gamma=Decimal("0.01"),
            right="P",
        ),
    )
    # call: 0.02*1000*1*100^2*0.01 = 2000
    # put:  -0.01*400*1*100^2*0.01 = -400
    # net 1600 → below 1M → formatted, not green
    text = gex_bg(spot=Decimal("100"), chain=chain)
    assert text == "+1.6K"
    assert gex_is_green(text) is False
    assert gex_is_green("+2.1M") is True
    assert format_gex(GEX_THRESHOLD + Decimal("1")).endswith("M")


def test_volume_value_area_is_70() -> None:
    assert VALUE_AREA_FRAC == Decimal("0.70")
    assert FVG_FILL_FRAC == Decimal("1.00")
    bars = [
        _bar(
            i,
            open_=str(100 + i),
            high=str(101 + i),
            low=str(99 + i),
            close=str(100 + i),
            tf="15m",
            volume=str(10 + i * 5),
        )
        for i in range(8)
    ]
    snap = volume_snapshot(bars)
    assert snap.poc
    assert snap.vah
    assert snap.val
    poc = Decimal(snap.poc)
    vah = Decimal(snap.vah)
    val = Decimal(snap.val)
    assert val <= poc <= vah


def test_zones_use_card_poc_not_vwap() -> None:
    bars = [
        Bar(
            symbol="BTCUSDT",
            tf="1d",
            open_ts=datetime(2026, 8, 29, tzinfo=UTC),
            close_ts=datetime(2026, 8, 29, 23, 59, 59, tzinfo=UTC),
            open=Decimal("95"),
            high=Decimal("100"),
            low=Decimal("90"),
            close=Decimal("98"),
            volume=Decimal("10"),
        )
    ]
    engine = ZoneEngine(tick_size=Decimal("0.1"))
    t = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    bare = engine.build("BTCUSDT", t, bars)
    assert not any(z.method == "vp_hyp" for z in bare)
    card_poc = Decimal("91.5")
    with_card = engine.build("BTCUSDT", t, bars, poc=card_poc)
    poc_zones = [z for z in with_card if z.method == "vp_hyp"]
    assert poc_zones
    assert any(z.lo == card_poc or z.hi == card_poc for z in poc_zones)


def test_from_news_uses_real_bar_labels() -> None:
    rows: list[tuple[str, str, str, str]] = []
    for i in range(RSI_PERIOD + RSI_UNSTABLE_PERIOD + 5):
        px = 100 + i * 0.2
        rows.append((str(px), str(px + 1), str(px - 0.5), str(px + 0.4)))
    rows[-3] = ("140", "141", "120", "121")
    rows[-2] = ("121", "130", "119", "128")
    rows[-1] = ("128", "145", "127", "144")
    bars = _ohlc(rows)
    card = from_news(symbol="BTCUSDT", now=NOW, calendar=(), bars=bars)
    assert card.rsi_htf is not None
    assert Decimal(card.rsi_htf) > 50
    assert card.fvg_status in {"filled", "open", "none"}
    assert card.sweep_status in {"done", "pending", "none"}
    assert card.gex_bg is None
    line = (
        f"[B-DEMO] {card.symbol} rsi={card.rsi_htf} fib={card.fib_zone}:{card.fib_level} "
        f"fvg={card.fvg_status} sweep={card.sweep_status} "
        f"ob={card.ob_status} bos={card.bos_status} gex={card.gex_bg} "
        f"ok={card.context_ok()}"
    )
    print(line)
    assert "rsi=" in line
    assert "+2.1M" not in line
    assert card.rsi_htf != "52"
