"""Drive already-decoded publicTrade frames. No keys. Socket is injected."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.types import MarketEvent


class BybitTradesWs:
    """Turns already-decoded JSON frames into MarketEvents.

    Opening a live socket is a caller concern (VPS, public endpoint, no keys).
    Does not invent a monotonic seq — Bybit publicTrade.seq may repeat.
    """

    def __init__(self, normalizer: TradesNormalizer | None = None) -> None:
        self.normalizer = normalizer or TradesNormalizer()

    def ingest_frames(
        self,
        frames: Iterable[dict[str, Any]],
        *,
        recv_ts: datetime | None = None,
    ) -> list[MarketEvent]:
        now = recv_ts or datetime.now(tz=UTC)
        out: list[MarketEvent] = []
        for frame in frames:
            out.extend(self.normalizer.normalize_frame(frame, recv_ts=now))
        return out
