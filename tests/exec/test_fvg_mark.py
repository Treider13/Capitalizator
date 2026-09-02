"""3-candle FVG is a journal flag. Not a zone. Not an entry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.fvg_mark import fvg_present
from capitalizator.zones.engine import ZoneEngine
from capitalizator.zones.model import Bar

CREATED = datetime(2026, 8, 31, 13, 0, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator"


def _bar(*, i: int, high: str, low: str, close: str | None = None) -> Bar:
    close_ts = CREATED + timedelta(minutes=15 * (i + 1))
    return Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=CREATED + timedelta(minutes=15 * i),
        close_ts=close_ts,
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close or low),
    )


def test_bullish_gap_when_third_low_above_first_high() -> None:
    bars = (
        _bar(i=0, high="100", low="99"),
        _bar(i=1, high="103", low="100.5"),
        _bar(i=2, high="104", low="101"),
    )
    assert fvg_present(bars, symbol="BTCUSDT", tf="15m", close_ts=bars[-1].close_ts) is True


def test_overlap_is_not_a_gap() -> None:
    bars = (
        _bar(i=0, high="100", low="99"),
        _bar(i=1, high="101", low="99.5"),
        _bar(i=2, high="100.5", low="99.2"),
    )
    assert fvg_present(bars, symbol="BTCUSDT", tf="15m", close_ts=bars[-1].close_ts) is False


def test_short_history_is_none() -> None:
    bars = (_bar(i=0, high="100", low="99"), _bar(i=1, high="101", low="100"))
    assert fvg_present(bars, symbol="BTCUSDT", tf="15m", close_ts=bars[-1].close_ts) is None


def test_hole_in_series_is_none() -> None:
    """NinjaTrader textbook is consecutive candles. A missing bar is not an FVG."""
    bars = (
        _bar(i=0, high="100", low="99"),
        _bar(i=1, high="103", low="100.5"),
        _bar(i=3, high="104", low="101"),
    )
    assert fvg_present(bars, symbol="BTCUSDT", tf="15m", close_ts=bars[-1].close_ts) is None


def test_zone_engine_still_has_no_fvg_method() -> None:
    text = (SRC / "zones" / "engine.py").read_text(encoding="utf-8")
    assert "no ICT/FVG" in text
    assert "fvg" not in ZoneEngine.__dict__


def test_jury_source_has_no_fvg() -> None:
    text = (SRC / "jury" / "desk.py").read_text(encoding="utf-8")
    assert "fvg" not in text
