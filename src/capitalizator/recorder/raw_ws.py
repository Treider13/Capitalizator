"""Raw Bybit v5 public WebSocket: frames exactly as the venue sends them.

Why not pybit's `WebSocket` here: pybit rebuilds the order book locally and hands
every callback a `type="snapshot"` with the full book (`_websocket_stream.py::
_process_normal_message`, verified on 5.17). The desk needs the *deltas* — the
ZLG gesture and the ОКО Shadow are built from new/pulled quotes inside the 8 s
window — so the recorder must see `type="delta"` frames untouched. Same for
`tickers`, where pybit merges deltas into a running snapshot.

This client (on `websocket-client`, which pybit already depends on):
  * one connection per `channel_type` (`linear` here), `wss://stream.bybit.com/v5/public/linear`
    or the testnet host;
  * `{"op":"ping"}` every 20 s (docs/v5/ws/connect) on its own timer; the venue's
    `pong` and subscribe acks are passed through as control frames;
  * subscribes in chunks of ≤10 args (spot limit; harmless on linear) and
    re-subscribes everything after a reconnect;
  * reconnects with capped exponential backoff; `is_connected()` for the watchdog;
  * routes each frame to the callback registered for its topic prefix
    (`publicTrade`, `orderbook`, `tickers`, `allLiquidation`).
No keys, no order path.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

Frame = Mapping[str, Any]
Callback = Callable[[Frame], None]

MAINNET_LINEAR = "wss://stream.bybit.com/v5/public/linear"
TESTNET_LINEAR = "wss://stream-testnet.bybit.com/v5/public/linear"
PING_INTERVAL_S = 20.0
SUBSCRIBE_CHUNK = 10
BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


class RawPublicWs:
    def __init__(
        self,
        *,
        testnet: bool = False,
        url: str | None = None,
        ping_interval_s: float = PING_INTERVAL_S,
        on_control: Callback | None = None,
        on_error: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url or (TESTNET_LINEAR if testnet else MAINNET_LINEAR)
        self.ping_interval_s = ping_interval_s
        self._routes: dict[str, Callback] = {}
        self._topics: list[str] = []
        self._on_control = on_control
        self._on_error = on_error
        self._clock = clock
        self._app: Any = None
        self._thread: threading.Thread | None = None
        self._pinger: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self.reconnects = 0
        self._attempt = 0
        self.frames = 0
        self.last_frame_mono: float | None = None
        self.last_pong_mono: float | None = None

    # --- subscriptions (pybit-shaped so LiveRecorder does not care which client) -------
    def trade_stream(self, symbols: Sequence[str] | str, callback: Callback) -> None:
        self._add("publicTrade", [f"publicTrade.{s}" for s in _seq(symbols)], callback)

    def orderbook_stream(
        self, depth: int, symbols: Sequence[str] | str, callback: Callback
    ) -> None:
        if depth not in {1, 50, 200, 500, 1000}:
            raise ValueError("linear orderbook depth must be 1/50/200/500/1000")
        self._add("orderbook", [f"orderbook.{depth}.{s}" for s in _seq(symbols)], callback)

    def ticker_stream(self, symbols: Sequence[str] | str, callback: Callback) -> None:
        self._add("tickers", [f"tickers.{s}" for s in _seq(symbols)], callback)

    def liquidation_stream(self, symbols: Sequence[str] | str, callback: Callback) -> None:
        self._add("allLiquidation", [f"allLiquidation.{s}" for s in _seq(symbols)], callback)

    def _add(self, prefix: str, topics: list[str], callback: Callback) -> None:
        self._routes[prefix] = callback
        new = [t for t in topics if t not in self._topics]
        self._topics.extend(new)
        if self._connected.is_set() and new:
            self._send_subscribe(new)

    # --- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bybit-public-ws", daemon=True)
        self._thread.start()
        self._pinger = threading.Thread(target=self._ping_loop, name="bybit-ws-ping", daemon=True)
        self._pinger.start()

    def exit(self) -> None:
        self._stop.set()
        app = self._app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        self._connected.clear()

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # --- internals -------------------------------------------------------------------------
    def _run(self) -> None:
        import websocket  # websocket-client, pulled in by pybit

        self._attempt = 0
        while not self._stop.is_set():
            app = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_ws_error,
                on_close=self._on_close,
            )
            self._app = app
            try:
                app.run_forever(ping_interval=0)  # we ping with the venue's `op` frame
            except Exception as exc:  # network layer; reconnect below
                self._report(f"run_forever: {exc}")
            self._connected.clear()
            if self._stop.is_set():
                break
            self.reconnects += 1
            delay = BACKOFF_S[min(self._attempt, len(BACKOFF_S) - 1)]
            self._attempt += 1
            self._stop.wait(delay)
        self._app = None

    def _ping_loop(self) -> None:
        while not self._stop.wait(self.ping_interval_s):
            if not self._connected.is_set():
                continue
            self._send({"op": "ping"})
            # half-open TCP: frames stop but the socket "is connected". No frame (data or
            # pong) for 2 intervals → close, run_forever returns, we reconnect (audit B11).
            last = max(self.last_frame_mono or 0.0, self.last_pong_mono or 0.0)
            if last and self._clock() - last > 2 * self.ping_interval_s:
                self._report("stale socket: no frames for 2 ping intervals, reconnecting")
                app = self._app
                if app is not None:
                    try:
                        app.close()
                    except Exception:
                        pass

    def _on_open(self, _app: Any) -> None:
        self._connected.set()
        self._attempt = 0  # a good connection resets the backoff (audit B11)
        self.last_frame_mono = self._clock()
        if self._topics:
            self._send_subscribe(list(self._topics))

    def _on_close(self, _app: Any, _code: Any, _msg: Any) -> None:
        self._connected.clear()

    def _on_ws_error(self, _app: Any, error: Any) -> None:
        self._report(str(error))

    def _on_message(self, _app: Any, message: str | bytes) -> None:
        self.frames += 1
        self.last_frame_mono = self._clock()
        try:
            frame = json.loads(message)
        except (ValueError, TypeError):
            self._report("non-json frame")
            return
        if not isinstance(frame, dict):
            return
        self.dispatch(frame)

    def dispatch(self, frame: Frame) -> None:
        """Route one decoded frame. Public so tests can feed frames without a socket."""
        topic = str(frame.get("topic") or "")
        if not topic:
            if frame.get("op") == "pong" or frame.get("ret_msg") == "pong":
                self.last_pong_mono = self._clock()
            if self._on_control is not None:
                self._on_control(frame)
            return
        prefix = topic.split(".", 1)[0]
        cb = self._routes.get(prefix)
        if cb is not None:
            cb(frame)

    def _send_subscribe(self, topics: list[str]) -> None:
        for i in range(0, len(topics), SUBSCRIBE_CHUNK):
            self._send({"op": "subscribe", "args": topics[i : i + SUBSCRIBE_CHUNK]})

    def _send(self, payload: Mapping[str, Any]) -> None:
        app = self._app
        if app is None:
            return
        try:
            app.send(json.dumps(payload))
        except Exception as exc:
            self._report(f"send: {exc}")

    def _report(self, msg: str) -> None:
        if self._on_error is not None:
            self._on_error(msg)


def _seq(symbols: Sequence[str] | str) -> list[str]:
    return [symbols] if isinstance(symbols, str) else list(symbols)
