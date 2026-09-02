"""CPI/FOMC day: before 13:30Z closed. Session open after. 24h cut is not this module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capitalizator.news_macro.ingest import NewsIngest, NewsRow
from capitalizator.risk.session import SessionWindow, load_time_config, us_data_known_at

MACRO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "macro.csv"
TIME_YAML = Path(__file__).resolve().parents[2] / "infra" / "time.yaml"


def test_cpi_morning_is_closed_session_is_open() -> None:
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 9, 11, 12, 0, tzinfo=UTC), news.rows)
    assert ok is False
    assert reason == "us_data_day"
    ok2, reason2 = win.allows(datetime(2026, 9, 11, 14, 10, tzinfo=UTC), news.rows)
    assert ok2 is True
    assert reason2 == "session"


def test_november_cpi_est_morning_is_closed() -> None:
    """10 Nov 2026 is EST. CPI 13:30Z. Morning still a US-data day."""
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 11, 10, 12, 0, tzinfo=UTC), news.rows)
    assert ok is False
    assert reason == "us_data_day"
    ok2, reason2 = win.allows(datetime(2026, 11, 10, 14, 10, tzinfo=UTC), news.rows)
    assert ok2 is True
    assert reason2 == "session"


def test_fomc_morning_is_closed() -> None:
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 9, 16, 12, 0, tzinfo=UTC), news.rows)
    assert ok is False
    assert reason == "us_data_day"


def test_unknown_row_is_not_us_data_day() -> None:
    """PIT: schedule we have not learned yet does not close the morning."""
    row = NewsRow(
        event_id="cpi-not-yet",
        event_class="CPI",
        event_time=datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
        known_at=datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
        assets=("BTCUSDT",),
        source="bls",
        announce_tz="America/New_York",
        size_rule="pre24_cut",
        notes="not in file yet",
        raw="",
    )
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 9, 11, 12, 0, tzinfo=UTC), [row])
    assert ok is False
    assert reason == "outside session"


def test_day_before_cpi_session_is_open() -> None:
    """24h pre-event cut is MacroRules 2.11.7. Session does not apply it."""
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 9, 10, 14, 10, tzinfo=UTC), news.rows)
    assert ok is True
    assert reason == "session"


def test_nfp_morning_is_closed_session_is_open() -> None:
    """4 Sep 2026 NFP 12:30Z. Morning closed; 14:10Z is the Moscow session."""
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 9, 4, 12, 0, tzinfo=UTC), news.rows)
    assert ok is False
    assert reason == "us_data_day"
    ok2, reason2 = win.allows(datetime(2026, 9, 4, 14, 10, tzinfo=UTC), news.rows)
    assert ok2 is True
    assert reason2 == "session"


def test_november_nfp_est_morning_is_closed() -> None:
    """6 Nov 2026 is EST. NFP 13:30Z. 12:00Z is still a US-data morning."""
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 11, 6, 12, 0, tzinfo=UTC), news.rows)
    assert ok is False
    assert reason == "us_data_day"
    ok2, reason2 = win.allows(datetime(2026, 11, 6, 14, 10, tzinfo=UTC), news.rows)
    assert ok2 is True
    assert reason2 == "session"


def test_pce_morning_is_closed() -> None:
    news = NewsIngest.from_csv(MACRO)
    win = SessionWindow()
    ok, reason = win.allows(datetime(2026, 9, 30, 12, 0, tzinfo=UTC), news.rows)
    assert ok is False
    assert reason == "us_data_day"


def test_quiet_day_has_no_us_data_known_at() -> None:
    news = NewsIngest.from_csv(MACRO)
    assert us_data_known_at(datetime(2026, 9, 2, 14, 10, tzinfo=UTC), news.rows) is None
    assert us_data_known_at(datetime(2026, 9, 11, 14, 10, tzinfo=UTC), news.rows) is not None


def test_time_yaml_is_phase_build_window() -> None:
    assert TIME_YAML.is_file()
    cfg = load_time_config()
    assert cfg["session_tz"] == "Europe/Moscow"
    assert cfg["session_start"] == "16:30"
    assert cfg["session_end"] == "19:30"
    assert list(cfg["us_data_classes"]) == ["CPI", "FOMC", "NFP", "PCE"]
