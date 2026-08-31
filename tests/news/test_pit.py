"""Slice before known_at does not see the news row. No invented times."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.news_macro.ingest import NewsIngest, NewsIngestError
from capitalizator.news_macro.store import NewsStore

ROOT = Path(__file__).resolve().parents[2]
MACRO = ROOT / "infra" / "calendars" / "macro.csv"


def test_repo_macro_csv_has_required_times() -> None:
    news = NewsIngest.from_csv(MACRO)
    assert {r.event_id for r in news.rows} == {
        "cpi-2026-09-11",
        "cpi-2026-10-14",
        "cpi-2026-11-10",
        "fomc-2026-09-16",
        "fomc-2026-10-28",
        "fomc-2026-12-09",
        "nfp-2026-09-04",
        "nfp-2026-10-02",
        "nfp-2026-11-06",
        "nfp-2026-12-04",
        "pce-2026-09-30",
        "pce-2026-10-29",
        "pce-2026-11-25",
        "pce-2026-12-23",
    }
    for row in news.rows:
        assert row.event_time.tzinfo is not None
        assert row.known_at.tzinfo is not None
        assert row.our_reaction_coef is None


def test_slice_before_known_at_is_empty() -> None:
    news = NewsIngest.from_csv(MACRO)
    before = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    assert news.visible(before) == []
    store = NewsStore(news.rows)
    assert store.query("SELECT event_id FROM news", as_of=before) == []


def test_slice_at_known_at_sees_rows() -> None:
    news = NewsIngest.from_csv(MACRO)
    when = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    seen = news.visible(when)
    assert len(seen) == 14
    store = NewsStore(news.rows)
    rows = store.query("SELECT event_id FROM news ORDER BY event_id", as_of=when)
    assert [r["event_id"] for r in rows] == sorted(r.event_id for r in seen)


def test_missing_known_at_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "event_id,class,event_time_utc,announce_tz,known_at_utc,assets,source,size_rule,notes\n"
        "x,CPI,2026-09-11T12:30:00Z,America/New_York,,BTCUSDT,bls,pre24_cut,n\n",
        encoding="utf-8",
    )
    with pytest.raises(NewsIngestError, match="known_at"):
        NewsIngest.from_csv(path)


def test_naive_event_time_rejected(tmp_path: Path) -> None:
    path = tmp_path / "naive.csv"
    path.write_text(
        "event_id,class,event_time_utc,announce_tz,known_at_utc,assets,source,size_rule,notes\n"
        "x,CPI,2026-09-11T12:30:00,America/New_York,2026-08-31T12:00:00Z,BTCUSDT,bls,pre24_cut,n\n",
        encoding="utf-8",
    )
    with pytest.raises(NewsIngestError, match="UTC"):
        NewsIngest.from_csv(path)


def test_december_fomc_is_est_1900z() -> None:
    """DST ended 1 Nov 2026; 14:00 ET on 9 Dec is 19:00Z, not 18:00Z."""
    news = NewsIngest.from_csv(MACRO)
    dec = next(r for r in news.rows if r.event_id == "fomc-2026-12-09")
    assert dec.event_time == datetime(2026, 12, 9, 19, 0, tzinfo=UTC)


def test_november_cpi_is_est_1330z() -> None:
    """DST ended 1 Nov 2026; 08:30 ET on 10 Nov is 13:30Z, not 12:30Z."""
    news = NewsIngest.from_csv(MACRO)
    nov = next(r for r in news.rows if r.event_id == "cpi-2026-11-10")
    assert nov.event_time == datetime(2026, 11, 10, 13, 30, tzinfo=UTC)


def test_nfp_pce_official_clocks() -> None:
    """BLS empsit + BEA schedule. Sep/Oct still EDT. After 1 Nov 2026 EST."""
    news = NewsIngest.from_csv(MACRO)
    times = {r.event_id: r.event_time for r in news.rows}
    assert times["nfp-2026-09-04"] == datetime(2026, 9, 4, 12, 30, tzinfo=UTC)
    assert times["nfp-2026-11-06"] == datetime(2026, 11, 6, 13, 30, tzinfo=UTC)
    assert times["nfp-2026-12-04"] == datetime(2026, 12, 4, 13, 30, tzinfo=UTC)
    assert times["pce-2026-09-30"] == datetime(2026, 9, 30, 12, 30, tzinfo=UTC)
    assert times["pce-2026-10-29"] == datetime(2026, 10, 29, 12, 30, tzinfo=UTC)
    assert times["pce-2026-12-23"] == datetime(2026, 12, 23, 13, 30, tzinfo=UTC)
    assert {r.event_class for r in news.rows if r.event_id.startswith("nfp-")} == {"NFP"}
    assert {r.event_class for r in news.rows if r.event_id.startswith("pce-")} == {"PCE"}
    assert all(r.size_rule == "us_data_day" for r in news.rows if r.event_class in {"NFP", "PCE"})
