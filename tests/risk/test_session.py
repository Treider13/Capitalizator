"""12:00 UTC reject, 14:10 UTC accept, 20:00 UTC reject. Night 5x always reject."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.news_macro.ingest import NewsIngest
from capitalizator.risk.session import SessionWindow, allow_entry, in_desk_window

MACRO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "macro.csv"


def test_1500_msk_is_closed() -> None:
    noon = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    assert in_desk_window(noon) is False
    ok, reason = allow_entry(noon)
    assert ok is False
    assert reason == "outside session"


def test_1710_msk_is_open() -> None:
    t = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
    assert in_desk_window(t) is True
    ok, reason = allow_entry(t)
    assert ok is True
    assert reason == "session"


def test_2300_msk_is_closed() -> None:
    t = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    ok, reason = allow_entry(t)
    assert ok is False
    assert reason == "outside session"


def test_night_five_x_always_reject() -> None:
    t = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    ok, reason = allow_entry(t, lev=Decimal("5"), no_us_today=True)
    assert ok is False
    assert reason == "night 5x"


def test_msk_window_does_not_shift_on_us_dst() -> None:
    """2026-03-08 US spring. MSK has no DST. 13:30Z is still 16:30 MSK."""
    t = datetime(2026, 3, 8, 13, 30, tzinfo=UTC)
    assert in_desk_window(t) is True


def test_cpi_day_before_session_is_closed() -> None:
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    before = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    ok, reason = win.allows(before, news.rows)
    assert ok is False
    assert reason == "us_data_day"
    during = datetime(2026, 9, 11, 14, 10, tzinfo=UTC)
    ok2, reason2 = win.allows(during, news.rows)
    assert ok2 is True
    assert reason2 == "session"


def test_no_us_today_logs_bypass() -> None:
    t = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    ok, reason = allow_entry(t, no_us_today=True)
    assert ok is True
    assert reason == "no_us_today"


def test_naive_datetime_is_rejected() -> None:
    win = SessionWindow()
    with pytest.raises(TypeError, match="naive"):
        win.allows(datetime(2026, 8, 31, 14, 10))


def test_session_does_not_import_macro_rules() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "risk" / "session.py"
    text = src.read_text(encoding="utf-8")
    assert "MacroRules" not in text
    assert "news_macro.rules" not in text


def test_session_source_has_no_handwritten_offset() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "risk" / "session.py"
    text = src.read_text(encoding="utf-8")
    assert "timedelta" not in text
    assert "UTC+" not in text
    assert "datetime.timezone" not in text
    assert "ZoneInfo" in text
