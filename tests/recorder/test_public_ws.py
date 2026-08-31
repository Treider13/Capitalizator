"""Official public linear WS names and control-frame skip. No live socket."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.recorder.public_ws import (
    PUBLIC_LINEAR_WS,
    book_topic,
    is_control_frame,
    subscribe_payload,
    trade_topic,
)
from capitalizator.recorder.ws_trades import BybitTradesWs

RECV = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)

# https://bybit-exchange.github.io/docs/v5/ws/connect
# https://bybit-exchange.github.io/docs/v5/websocket/public/trade


def test_public_url_is_official_mainnet_linear() -> None:
    assert PUBLIC_LINEAR_WS == "wss://stream.bybit.com/v5/public/linear"


def test_topics_match_phase_build_and_docs() -> None:
    assert trade_topic("BTCUSDT") == "publicTrade.BTCUSDT"
    assert book_topic("BTCUSDT") == "orderbook.200.BTCUSDT"


def test_subscribe_payload() -> None:
    assert subscribe_payload("BTCUSDT", "trades") == {
        "op": "subscribe",
        "args": ["publicTrade.BTCUSDT"],
    }
    assert subscribe_payload("ETHUSDT", "book") == {
        "op": "subscribe",
        "args": ["orderbook.200.ETHUSDT"],
    }


def test_bad_book_depth_rejected() -> None:
    with pytest.raises(ValueError, match="depth"):
        book_topic("BTCUSDT", depth=99)


def test_run_skips_subscribe_ack_and_ping() -> None:
    ack = {"success": True, "ret_msg": "subscribe", "conn_id": "x", "op": "subscribe"}
    ping = {"op": "ping"}
    trade = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "1", "i": "a", "seq": 9},
        ],
    }
    events = BybitTradesWs().run([ack, ping, trade], recv_ts=RECV)
    assert len(events) == 1
    assert events[0].payload["px"] == "1"


def test_control_frame_with_topic_is_not_skipped() -> None:
    """A market frame must not be dropped just because someone added op."""
    frame = {
        "topic": "publicTrade.BTCUSDT",
        "op": "subscribe",
        "data": [
            {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "1", "i": "a"},
        ],
    }
    assert is_control_frame(frame) is False
    assert len(BybitTradesWs().run([frame], recv_ts=RECV)) == 1
