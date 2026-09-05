"""CSV owns scheduled clocks. Intel surprises share the same merge as propose."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from capitalizator.card.build import from_news
from capitalizator.card.live import VolumeSnapshot
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.merge import merged_calendar, screen_events
from capitalizator.news_macro.rules import MacroRules

NOW = datetime(2026, 9, 10, 19, 0, tzinfo=UTC)
CPI_PRINT = datetime(2026, 9, 11, 12, 30, tzinfo=UTC)  # 08:30 ET


def _row(
    *,
    event_id: str,
    klass: str,
    event_time: datetime,
    known_at: datetime | None = None,
    source: str = "csv",
    notes: str = "",
) -> NewsRow:
    return NewsRow(
        event_id=event_id,
        event_class=klass,
        event_time=event_time,
        known_at=known_at or event_time,
        assets=("BTCUSDT",),
        source=source,
        announce_tz="UTC",
        size_rule=source,
        notes=notes,
        raw=notes,
    )


def test_rss_cpi_does_not_move_event_window() -> None:
    csv = (_row(event_id="cpi-csv", klass="CPI", event_time=CPI_PRINT, known_at=NOW),)
    rss = (
        _row(
            event_id="cpi-rss",
            klass="CPI",
            event_time=NOW,
            known_at=NOW,
            source="rss",
            notes="CPI chatter",
        ),
    )
    merged = merged_calendar(csv=csv, intel=rss, now=NOW)
    assert [r.event_id for r in merged] == ["cpi-csv"]
    rules = MacroRules(enabled=True)
    around_rss = rules.decide(NOW, merged)
    assert around_rss.reason != "event_window_CPI"
    around_print = rules.decide(CPI_PRINT, merged)
    assert around_print.reason == "event_window_CPI"


def test_hack_without_csv_is_in_merge_and_vetoes_card() -> None:
    hack = _row(
        event_id="rss-hack",
        klass="HACK",
        event_time=NOW,
        known_at=NOW,
        source="intel",
        notes="hot wallet hack",
    )
    merged = merged_calendar(csv=(), intel=(hack,), now=NOW)
    assert len(merged) == 1 and merged[0].event_class == "HACK"
    card = from_news(
        symbol="BTCUSDT",
        now=NOW,
        calendar=merged,
        volume=VolumeSnapshot(rvol="3"),
    )
    assert card.bearing_verdict == "veto"
    assert "coin_negative" in card.minuses


def test_rss_cpi_without_csv_is_not_a_clock() -> None:
    rss = (
        _row(
            event_id="cpi-rss",
            klass="CPI",
            event_time=NOW + timedelta(hours=1),
            known_at=NOW,
            source="rss",
            notes="US CPI due",
        ),
    )
    merged = merged_calendar(csv=(), intel=rss, now=NOW)
    assert merged == ()
    assert MacroRules(enabled=True).decide(NOW + timedelta(minutes=30), merged).reason == "ok"
    card = from_news(
        symbol="BTCUSDT",
        now=NOW,
        calendar=merged,
        volume=VolumeSnapshot(rvol="3"),
    )
    assert card.bearing_verdict != "veto"
    assert "fomc_inside_2h" not in card.minuses


def test_duplicate_event_id_is_kept_once() -> None:
    row = _row(event_id="same", klass="HACK", event_time=NOW, notes="hack")
    merged = merged_calendar(csv=(row,), intel=(row,), now=NOW)
    assert len(merged) == 1


def test_screen_same_ny_date_marks_clock_csv() -> None:
    csv = (_row(event_id="cpi-csv", klass="CPI", event_time=CPI_PRINT, known_at=NOW),)
    rss = (
        _row(
            event_id="cpi-rss",
            klass="CPI",
            event_time=CPI_PRINT.replace(hour=19),
            known_at=NOW,
            source="rss",
            notes="CPI chatter same NY date",
        ),
    )
    events = {e["event_id"]: e for e in screen_events(csv=csv, intel=rss, now=NOW)}
    assert events["cpi-rss"]["clock"] == "csv"
    assert events["cpi-rss"]["kind"] == "intel_headline"
    merged = merged_calendar(csv=csv, intel=rss, now=NOW)
    assert [r.event_id for r in merged] == ["cpi-csv"]


def test_other_without_negative_token_is_not_a_clock() -> None:
    meh = _row(
        event_id="rss-meh",
        klass="OTHER",
        event_time=NOW,
        source="intel",
        notes="Market wrap: volumes steady",
    )
    assert merged_calendar(csv=(), intel=(meh,), now=NOW) == ()
    assert screen_events(csv=(), intel=(meh,), now=NOW) == []


def test_other_with_negative_token_is_a_surprise() -> None:
    halt = _row(
        event_id="rss-halt",
        klass="OTHER",
        event_time=NOW,
        source="intel",
        notes="Spot halt on venue",
    )
    merged = merged_calendar(csv=(), intel=(halt,), now=NOW)
    assert len(merged) == 1 and merged[0].event_id == "rss-halt"


def test_screen_keeps_scheduled_headline_without_a_second_clock() -> None:
    csv = (_row(event_id="cpi-csv", klass="CPI", event_time=CPI_PRINT, known_at=NOW),)
    rss = (
        _row(
            event_id="cpi-rss",
            klass="CPI",
            event_time=NOW,
            known_at=NOW,
            source="rss",
            notes="CPI chatter",
        ),
    )
    events = screen_events(csv=csv, intel=rss, now=NOW)
    origins = {e["event_id"]: e for e in events}
    assert origins["cpi-csv"]["origin"] == "csv" and origins["cpi-csv"]["clock"] == "csv"
    assert origins["cpi-rss"]["origin"] == "intel"
    assert origins["cpi-rss"]["kind"] == "intel_headline"
    assert origins["cpi-rss"]["clock"] == "none"
