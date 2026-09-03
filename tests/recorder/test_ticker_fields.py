"""Funding payload carries the settlement clock, the live interval and 24h turnover."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.recorder.live import ticker_events
from capitalizator.recorder.rest_ticker import RestTicker
from capitalizator.recorder.ticker_fields import funding_payload

NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def test_payload_fields_when_present_and_absent_when_missing() -> None:
    full = funding_payload({"fundingRate": "0.0001", "nextFundingTime": "1760342400000",
                            "fundingIntervalHour": "1", "turnover24h": "4936790807.6521"})
    assert full == {"funding": "0.0001", "next_funding_ts": "1760342400000",
                    "interval_min": "60", "turnover24h": "4936790807.6521"}
    minimal = funding_payload({"fundingRate": "-0.005"})
    assert minimal == {"funding": "-0.005"}  # no default of 8 hours anywhere


@pytest.mark.parametrize(
    "item",
    [
        {"fundingRate": "0", "nextFundingTime": "soon"},
        {"fundingRate": "0", "fundingIntervalHour": "0"},
        {"fundingRate": "0", "fundingIntervalHour": "eight"},
        {"fundingRate": "0", "turnover24h": "lots"},
    ],
)
def test_bad_fields_are_errors_not_zeros(item: dict) -> None:
    with pytest.raises(ValueError):
        funding_payload(item)


def test_ws_and_rest_parsers_share_the_payload() -> None:
    item = {"symbol": "BTCUSDT", "fundingRate": "0.0001", "nextFundingTime": "1760342400000",
            "fundingIntervalHour": "8", "turnover24h": "1", "openInterest": "5", "markPrice": "7"}
    ws = ticker_events({"topic": "tickers.BTCUSDT", "type": "snapshot", "ts": 1760325052630,
                        "data": item}, recv_ts=NOW)
    funding = next(e for e in ws if e.stream == "funding")
    assert funding.payload["interval_min"] == "480" and funding.payload["turnover24h"] == "1"
    rest = RestTicker().parse({"retCode": 0, "result": {"list": [item]}}, recv_ts=NOW)
    assert next(e for e in rest if e.stream == "funding").payload == funding.payload
