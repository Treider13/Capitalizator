"""Raw public WS: preserve delta semantics; every reconnect gets a new generation."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any


class RawPublic:
    def __init__(
        self,
        symbols: tuple[str, ...],
        callback: Callable[[dict[str, Any]], None],
        *,
        factory: Any = None,
        category: str = "linear",
    ) -> None:
        if category not in {"linear", "spot"} or not symbols:
            raise ValueError("nonempty linear/spot subscription required")
        if category == "spot" and len(symbols) > 10:
            raise ValueError("spot subscriptions exceed per-request topic limit")
        if factory is None:
            from websocket import WebSocketApp

            factory = WebSocketApp
        self.started_at = time.time()
        self.started_at_monotonic = time.monotonic()
        self.callback = callback
        topics = (
            ("orderbook.50",)
            if category == "spot"
            else ("orderbook.50", "publicTrade", "tickers", "allLiquidation")
        )
        self.topics = [f"{topic}.{symbol}" for symbol in symbols for topic in topics]
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.error = ""
        self.last_message = time.monotonic()
        self.last_data_message = self.last_message
        self.ws = factory(
            "wss://stream.bybit.com/v5/public/" + category,
            on_open=self._open,
            on_message=self._message,
            on_error=self._error,
            on_close=self._close,
        )
        self.thread = threading.Thread(target=self._run, name=category + "-wire", daemon=True)
        self.heartbeat = threading.Thread(
            target=self._ping, name=category + "-heartbeat", daemon=True
        )
        self.thread.start()
        self.heartbeat.start()

    def _open(self, ws: Any) -> None:
        # Subscription acknowledgements, not TCP establishment, determine readiness.
        ws.send(json.dumps({"op": "subscribe", "args": self.topics}))

    def _message(self, ws: Any, message: str) -> None:
        try:
            frame = json.loads(message)
            self.last_message = time.monotonic()
            if frame.get("op") == "subscribe":
                if frame.get("success") is not True:
                    raise ValueError("public subscription rejected")
                self.connected.set()
            elif frame.get("topic") in self.topics:
                self.last_data_message = time.monotonic()
                self.callback(frame)  # No SDK accumulation or snapshot rewriting.
        except Exception as exc:
            self._error(ws, exc)
            ws.close()

    def _error(self, ws: Any, error: Any) -> None:
        self.error = type(error).__name__
        self.connected.clear()

    def _close(self, ws: Any, *args: Any) -> None:
        self.connected.clear()
        self.closed.set()

    def _run(self) -> None:
        try:
            self.ws.run_forever(reconnect=0)
        finally:
            self.connected.clear()
            self.closed.set()

    def _ping(self) -> None:
        # Bybit application heartbeat. This wait never runs on a market/account actor.
        while not self.closed.wait(20):
            try:
                if self.connected.is_set():
                    self.ws.send(json.dumps({"op": "ping"}))
                if time.monotonic() - self.last_message > 40:
                    self.ws.close()
            except Exception as exc:
                self._error(self.ws, exc)
                self.ws.close()

    def is_connected(self) -> bool:
        return self.connected.is_set() and not self.closed.is_set()

    def exit(self) -> None:
        self.closed.set()
        self.connected.clear()
        self.ws.close()
        for thread in (self.thread, self.heartbeat):
            if thread is not threading.current_thread():
                thread.join(5)
                if thread.is_alive():
                    raise RuntimeError(f"{thread.name} failed to close")
