"""0.2.1 — REST snapshot. Official Bybit field names, no invented depth."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.recorder.rest_snapshot import RestSnapshot

# https://bybit-exchange.github.io/docs/v5/market/orderbook
OFFICIAL_REST = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "s": "BTCUSDT",
        "a": [["65557.7", "16.606555"]],
        "b": [["65485.47", "47.081829"]],
        "ts": 1716863719031,
        "u": 230704,
        "seq": 1432604333,
        "cts": 1716863718905,
    },
    "retExtInfo": {},
    "time": 1716863719382,
}


def test_parse_official_bybit_rest_example() -> None:
    snap = RestSnapshot().parse(OFFICIAL_REST)
    assert snap.symbol == "BTCUSDT"
    assert snap.seq == 230704  # u, not cross seq
    assert snap.cross_seq == 1432604333
    # cts (matching engine), not ts (system). Official example: 126 ms apart.
    assert snap.exchange_ts == datetime.fromtimestamp(1716863718905 / 1000, tz=UTC)
    assert snap.system_ts == datetime.fromtimestamp(1716863719031 / 1000, tz=UTC)
    assert snap.bids == (("65485.47", "47.081829"),)
    assert snap.asks == (("65557.7", "16.606555"),)


def test_cts_is_exchange_ts_when_ts_differs() -> None:
    snap = RestSnapshot().parse(OFFICIAL_REST)
    assert snap.exchange_ts != snap.system_ts
    assert snap.exchange_ts == datetime.fromtimestamp(
        OFFICIAL_REST["result"]["cts"] / 1000, tz=UTC
    )


def test_parse_uses_u_not_cross_seq_as_apply_id() -> None:
    """A hole in Bybit `seq` is normal. Applying it as u would false-gap."""
    snap = RestSnapshot().parse(OFFICIAL_REST)
    assert snap.seq != snap.cross_seq
    assert snap.seq == OFFICIAL_REST["result"]["u"]


def test_parse_rejects_nonzero_retcode() -> None:
    with pytest.raises(ValueError, match="retCode"):
        RestSnapshot().parse({"retCode": 10001, "retMsg": "no"})


def test_parse_rejects_missing_u() -> None:
    payload = {
        "retCode": 0,
        "result": {
            "s": "BTCUSDT",
            "ts": 1,
            "seq": 99,
            "b": [["1", "1"]],
            "a": [["2", "1"]],
        },
    }
    with pytest.raises(ValueError, match="missing u"):
        RestSnapshot().parse(payload)


def test_parse_rejects_missing_symbol() -> None:
    payload = {
        "retCode": 0,
        "result": {"ts": 1, "u": 1, "b": [["1", "1"]], "a": [["2", "1"]]},
    }
    with pytest.raises(ValueError, match="missing s"):
        RestSnapshot().parse(payload)


def test_parse_rejects_nonpositive_price() -> None:
    payload = {
        "retCode": 0,
        "result": {
            "s": "BTCUSDT",
            "ts": 1,
            "u": 1,
            "b": [["0", "1"]],
            "a": [["2", "1"]],
        },
    }
    with pytest.raises(ValueError, match="price"):
        RestSnapshot().parse(payload)


def test_parse_rejects_negative_size() -> None:
    payload = {
        "retCode": 0,
        "result": {
            "s": "BTCUSDT",
            "ts": 1,
            "u": 1,
            "b": [["1", "-2"]],
            "a": [["2", "1"]],
        },
    }
    with pytest.raises(ValueError, match="size"):
        RestSnapshot().parse(payload)


def test_parse_rejects_zero_depth() -> None:
    payload = {
        "retCode": 0,
        "result": {"s": "BTCUSDT", "ts": 1, "u": 1, "b": [], "a": [["2", "1"]]},
    }
    with pytest.raises(ValueError, match="depth"):
        RestSnapshot().parse(payload)


def test_fetch_uses_injected_opener_and_public_url() -> None:
    captured: list[str] = []

    def opener(url: str) -> bytes:
        captured.append(url)
        import json

        return json.dumps(OFFICIAL_REST).encode()

    snap = RestSnapshot().fetch("ETHUSDT", opener=opener)
    assert captured[0].startswith("https://api.bybit.com/v5/market/orderbook?")
    assert "category=linear" in captured[0]
    assert "symbol=ETHUSDT" in captured[0]
    assert "limit=200" in captured[0]
    assert "apiKey" not in captured[0]
    assert snap.seq == 230704


def test_to_event_is_snapshot_stream() -> None:
    recv = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    snap = RestSnapshot().parse(OFFICIAL_REST)
    event = RestSnapshot().to_event(snap, recv_ts=recv)
    assert event.stream == "snapshot"
    assert event.seq == 230704
    assert event.payload["cross_seq"] == 1432604333


def test_live_public_snapshot_optional() -> None:
    """Network is optional. Skip is honest; a fake 200 is not."""
    try:
        snap = RestSnapshot().fetch("BTCUSDT")
    except OSError:
        pytest.skip("no egress to api.bybit.com")
    assert snap.seq >= 0
    assert snap.bids and snap.asks
    assert snap.exchange_ts.tzinfo is not None
