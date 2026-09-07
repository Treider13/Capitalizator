from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from capitalizator.fusion import macro, macro_fallback


def page(month="September", year=2026, next_month="oct26"):
    return f"""<p>all Eastern Time</p>
<td class="ts-data-table-head">{month} {year}</td>
<a href="/research/calendars/i-{next_month}.html">NEXT MONTH</a>
<td class="somatdR"><div>04<br><a>Employment Situation</a><br>(08:30)</div></td>
<td class="somatdR"><div>11<br><a>Consumer Price Index</a><br>(08:30)</div></td>""".encode()


@pytest.mark.parametrize("month,number,hour", [("September", 9, 12), ("December", 12, 13)])
def test_calendar_preserves_published_time_and_source(month, number, hour):
    rows, link = macro_fallback.parse_month(page(month), macro_fallback.URL, 100, (2026, number))
    assert {r.event_class for r in rows} == {"CPI", "NFP"}
    assert all(r.event_time.hour == hour and r.event_time.minute == 30 for r in rows)
    assert all(r.known_at.timestamp() == 100 and r.source == macro_fallback.URL for r in rows)
    assert link == "https://www.newyorkfed.org/research/calendars/i-oct26.html"


@pytest.mark.parametrize(
    "old,new",
    [
        (b"all Eastern Time", b"UTC"),
        (b"September 2026", b"September 2025"),
        (b"(08:30)", b"TBD"),
        (b"Consumer Price Index", b"Producer Price Index"),
        (b"/research/calendars/i-oct26.html", b"https://example.org/calendar"),
        (b"NEXT MONTH", b"PREVIOUS MONTH"),
    ],
)
def test_incomplete_or_changed_calendar_is_not_ready(old, new):
    with pytest.raises(ValueError):
        macro_fallback.parse_month(page().replace(old, new), macro_fallback.URL, 100, (2026, 9))


def test_duplicate_event_is_rejected():
    raw = page() + b'<td class="somatdR">15<a>Consumer Price Index</a>(08:30)</td>'
    with pytest.raises(ValueError, match="duplicate"):
        macro_fallback.parse_month(raw, macro_fallback.URL, 100, (2026, 9))


def test_bls_forbidden_uses_two_real_months_and_retains_provenance(monkeypatch):
    def forbidden(*args):
        raise HTTPError(macro.SOURCES["bls"], 403, "Forbidden", {}, None)

    monkeypatch.setattr(macro, "read_url", forbidden)
    calls = []

    def read(url, timeout):
        calls.append(url)
        return page() if url == macro_fallback.URL else page("October", next_month="nov26")

    monkeypatch.setattr(macro_fallback, "read_url", read)
    at = datetime(2026, 9, 7, tzinfo=UTC).timestamp()
    rows = macro.fetch("bls", 10, at)
    assert len(calls) == 2
    assert {r.event_time.month for r in rows} == {9, 10}
    assert any(r.event_class == "NFP" and r.event_time.timestamp() > at for r in rows)
    assert all("newyorkfed.org" in r.source for r in rows)
    health = {"bls": {"ok": True, "at": at}}
    assert not any(
        "bls" in v or "CPI" in v or "NFP" in v for v in macro.coverage(tuple(rows), health, at, 60)
    )
    assert "macro_source:bls" in macro.coverage(tuple(rows), health, at + 61, 60)


def test_next_month_cannot_silently_repeat_current(monkeypatch):
    monkeypatch.setattr(macro_fallback, "read_url", lambda *args: page())
    with pytest.raises(ValueError, match="month mismatch"):
        macro_fallback.fetch(10, datetime(2026, 9, 7, tzinfo=UTC).timestamp())


def test_december_fetches_next_year(monkeypatch):
    monkeypatch.setattr(
        macro_fallback,
        "read_url",
        lambda url, timeout: (
            page("December", next_month="jan27")
            if url == macro_fallback.URL
            else page("January", 2027, "feb27")
        ),
    )
    rows = macro_fallback.fetch(10, datetime(2026, 12, 31, tzinfo=UTC).timestamp())
    assert {r.event_time.year for r in rows} == {2026, 2027}


def test_bea_failure_does_not_use_cpi_calendar(monkeypatch):
    monkeypatch.setattr(macro, "read_url", lambda *args: b"invalid calendar")
    with pytest.raises(ValueError, match="complete iCalendar"):
        macro.fetch("bea", 10, 100)


def test_valid_bls_does_not_request_fallback(monkeypatch):
    body = b'''BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Consumer Price Index
DTSTART:20260911T123000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Employment Situation
DTSTART:20261002T123000Z
END:VEVENT
END:VCALENDAR'''
    monkeypatch.setattr(macro, "read_url", lambda *args: body)
    monkeypatch.setattr(macro_fallback, "read_url", lambda *args: pytest.fail("unexpected fallback"))
    rows = macro.fetch("bls", 10, datetime(2026, 9, 7, tzinfo=UTC).timestamp())
    assert all(r.source == macro.SOURCES["bls"] for r in rows)
