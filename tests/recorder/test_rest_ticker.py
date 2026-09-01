"""§6.1 — funding / OI / mark REST parse. Fetch is injectable. No keys."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.recorder.rest_ticker import RestTicker

NOW = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)

PAYLOAD = {
    "retCode": 0,
    "result": {
        "category": "linear",
        "list": [
            {
                "symbol": "BTCUSDT",
                "fundingRate": "0.0001",
                "openInterest": "12",
                "markPrice": "65000.1",
                "ts": 1725024600000,
            }
        ],
    },
}


def test_parse_emits_funding_oi_mark() -> None:
    events = RestTicker().parse(PAYLOAD, recv_ts=NOW)
    streams = {e.stream for e in events}
    assert streams == {"funding", "oi", "mark"}
    by_stream = {e.stream: e for e in events}
    assert by_stream["funding"].payload["funding"] == "0.0001"
    assert by_stream["oi"].payload["oi"] == "12"
    assert by_stream["mark"].payload["mark"] == "65000.1"
    assert by_stream["mark"].symbol == "BTCUSDT"


def test_retcode_rejects() -> None:
    with pytest.raises(ValueError, match="retCode"):
        RestTicker().parse({"retCode": 10001, "result": {"list": []}}, recv_ts=NOW)


def test_fetch_uses_injected_opener() -> None:
    hits: list[str] = []

    def opener(url: str) -> dict:
        hits.append(url)
        return PAYLOAD

    events = RestTicker().fetch("BTCUSDT", recv_ts=NOW, opener=opener)
    assert hits and "tickers" in hits[0] and "BTCUSDT" in hits[0]
    assert {e.stream for e in events} == {"funding", "oi", "mark"}
