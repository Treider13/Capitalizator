"""Official Bybit *public* linear WS names. No keys. No socket here.

https://bybit-exchange.github.io/docs/v5/ws/connect
https://bybit-exchange.github.io/docs/v5/websocket/public/trade
https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook

PHASE-BUILD week 1 topic: publicTrade.BTCUSDT
PHASE-BUILD week 2 topic: orderbook.200.BTCUSDT
"""

from __future__ import annotations

from typing import Any

PUBLIC_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"
BOOK_DEPTH = 200


def trade_topic(symbol: str) -> str:
    return f"publicTrade.{symbol}"


def book_topic(symbol: str, *, depth: int = BOOK_DEPTH) -> str:
    if depth not in {1, 50, 200, 1000}:
        raise ValueError(f"Bybit linear orderbook depth must be 1/50/200/1000, got {depth}")
    return f"orderbook.{depth}.{symbol}"


def subscribe_payload(symbol: str, stream: str) -> dict[str, Any]:
    if stream == "trades":
        args = [trade_topic(symbol)]
    elif stream == "book":
        args = [book_topic(symbol)]
    else:
        raise ValueError(f"unknown stream {stream!r}")
    return {"op": "subscribe", "args": args}


def is_control_frame(frame: dict[str, Any]) -> bool:
    """Subscribe/ping acks are not market data. Official `op` field."""
    if frame.get("topic"):
        return False
    return frame.get("op") in {"ping", "pong", "subscribe", "unsubscribe", "auth"}
