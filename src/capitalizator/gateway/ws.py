"""Private WebSocket → PositionTracker, via pybit's threaded WebSocket client.

pybit runs callbacks on its own thread; we only enqueue the frame and let the
signer loop drain the queue on its thread (no shared mutable state in callbacks).
The factory is injected so the plumbing is unit-tested without a socket.
Frame shape: {"topic": "position"|"execution"|"order"|"wallet", "data": [...]}.
"""

from __future__ import annotations

import queue
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from capitalizator.gateway.keys import Keys
from capitalizator.gateway.tracker import PositionTracker

Frame = Mapping[str, Any]


def make_private_ws(keys: Keys) -> Any:
    from pybit.unified_trading import WebSocket

    return WebSocket(
        testnet=keys.testnet,
        channel_type="private",
        api_key=keys.api_key,
        api_secret=keys.api_secret,
        ping_interval=20,
        ping_timeout=10,
        retries=200,
        restart_on_error=True,
    )


class PrivateFeed:
    def __init__(self, tracker: PositionTracker, *, ws: Any | None = None) -> None:
        self.tracker = tracker
        self.ws = ws
        self.q: queue.Queue[Frame] = queue.Queue(maxsize=100_000)
        self.dropped = 0
        self.frames = 0
        self.last_frame_at: datetime | None = None

    def start(self) -> None:
        """Subscribe the four private topics. No-op without a ws (offline)."""
        if self.ws is None:
            return
        self.ws.position_stream(self.enqueue)
        self.ws.execution_stream(self.enqueue)
        self.ws.order_stream(self.enqueue)
        self.ws.wallet_stream(self.enqueue)

    def enqueue(self, frame: Frame) -> None:
        """pybit callback thread: park the frame, nothing else."""
        try:
            self.q.put_nowait(frame)
        except queue.Full:
            self.dropped += 1

    def drain(self, *, now: datetime | None = None, max_frames: int = 10_000) -> int:
        """Signer thread: apply parked frames to the tracker."""
        when = now or datetime.now(tz=UTC)
        n = 0
        while n < max_frames:
            try:
                frame = self.q.get_nowait()
            except queue.Empty:
                break
            self.apply(frame, now=when)
            n += 1
        return n

    def apply(self, frame: Frame, *, now: datetime) -> None:
        topic = str(frame.get("topic") or "")
        data = frame.get("data")
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        self.frames += 1
        self.last_frame_at = now
        if topic.startswith("position"):
            self.tracker.on_position(rows, now=now)
        elif topic.startswith("execution"):
            self.tracker.on_execution(rows)
        elif topic.startswith("order"):
            self.tracker.on_order(rows)
        elif topic.startswith("wallet"):
            self.tracker.on_wallet(rows, now=now)


FeedFactory = Callable[[Keys], Any]
