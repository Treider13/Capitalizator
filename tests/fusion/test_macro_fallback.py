from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from capitalizator.fusion import macro, macro_fallback


def page(month="September", year=2026, next_month="oct26"):
    navigation = (
        f'<a href="/research/calendars/i-{next_month}.html">NEXT MONTH</a>'
        if next_month is not None
        else ""
    )
    return f"""<p>all Eastern Time</p>
<td class="ts-data-table-head">{month} {year}</td>
{navigation}
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


@pytest.mark.parametrize("third_month", ["nov26", None])
def test_bls_forbidden_uses_two_real_months_and_retains_provenance(monkeypatch, third_month):
    def forbidden(*args):
        raise HTTPError(macro.SOURCES["bls"], 403, "Forbidden", {}, None)

    monkeypatch.setattr(macro, "read_url", forbidden)
    calls = []

    def read(url, timeout):
        calls.append(url)
        return page() if url == macro_fallback.URL else page("October", next_month=third_month)

    monkeypatch.setattr(macro_fallback, "read_url", read)
    at = datetime(2026, 9, 7, tzinfo=UTC).timestamp()
    rows = macro.fetch("bls", 10, at)
    assert calls == [
        macro_fallback.URL,
        "https://www.newyorkfed.org/research/calendars/i-oct26.html",
    ]
    assert len(rows) == 4
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


@pytest.mark.parametrize(
    "old,new,error",
    [
        (b"all Eastern Time", b"UTC", "missing timezone"),
        (b"October 2026", b"October 2025", "month mismatch"),
        (b"(08:30)", b"TBD", "release time"),
        (b"Consumer Price Index", b"Producer Price Index", "coverage incomplete"),
        (b">11<", b">32<", "day"),
    ],
)
def test_next_month_without_navigation_still_requires_valid_events(monkeypatch, old, new, error):
    following = page("October", next_month=None).replace(old, new)
    monkeypatch.setattr(
        macro_fallback, "read_url", lambda url, timeout: page() if url == macro_fallback.URL else following
    )
    with pytest.raises(ValueError, match=error):
        macro_fallback.fetch(10, datetime(2026, 9, 7, tzinfo=UTC).timestamp())


def test_december_fetches_next_year(monkeypatch):
    monkeypatch.setattr(
        macro_fallback,
        "read_url",
        lambda url, timeout: (
            page("December", next_month="jan27")
            if url == macro_fallback.URL
            else page("January", 2027, None)
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


@pytest.mark.parametrize("primary_status", [403, 429])
@pytest.mark.parametrize(
    "fallback_error",
    [
        ValueError("NY Fed monthly CPI/NFP coverage incomplete"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        TimeoutError("NY Fed timed out"),
        HTTPError(macro_fallback.URL, 503, "Service Unavailable", {}, None),
    ],
)
def test_failed_fallback_preserves_primary_http_status(monkeypatch, primary_status, fallback_error):
    primary = HTTPError(macro.SOURCES["bls"], primary_status, "BLS unavailable", {}, None)

    def fail_primary(*args):
        raise primary

    def fail_fallback(*args):
        raise fallback_error

    monkeypatch.setattr(macro, "read_url", fail_primary)
    monkeypatch.setattr(macro_fallback, "fetch", fail_fallback)
    with pytest.raises(HTTPError) as error:
        macro.fetch("bls", 10, 100)
    assert error.value is primary
    assert error.value.code == primary_status
    assert error.value.__cause__ is fallback_error


def test_non_http_primary_failure_preserves_fallback_error(monkeypatch):
    fallback_error = ValueError("NY Fed calendar month mismatch")

    def fail_fallback(*args):
        raise fallback_error

    monkeypatch.setattr(macro, "read_url", lambda *args: b"invalid calendar")
    monkeypatch.setattr(macro_fallback, "fetch", fail_fallback)
    with pytest.raises(ValueError) as error:
        macro.fetch("bls", 10, 100)
    assert error.value is fallback_error


def test_macro_worker_reports_primary_http_status_after_invalid_fallback(monkeypatch, tmp_path):
    from capitalizator.fusion.config import Config
    from capitalizator.fusion.runtime import Runtime

    def forbidden(*args):
        raise HTTPError(macro.SOURCES["bls"], 403, "Forbidden", {}, None)

    monkeypatch.setattr(macro, "SOURCES", {"bls": macro.SOURCES["bls"]})
    monkeypatch.setattr(macro, "read_url", forbidden)
    monkeypatch.setattr(macro_fallback, "read_url", lambda *args: b"invalid calendar")
    runtime = Runtime(tmp_path, Config())
    monkeypatch.setattr(runtime.supervisor, "beat", lambda name: runtime.supervisor.stop.set())
    try:
        runtime._macro()
        health = runtime.shared.macro_health["bls"]
        assert health["ok"] is False
        assert health["source"] == macro.SOURCES["bls"]
        assert health["http_status"] == 403
        assert runtime.shared.macro_calendar == ()
    finally:
        runtime.store.close()
