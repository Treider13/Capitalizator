"""Drive trade frames through the normalizer. No keys. Socket is injected."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from capitalizator.recorder.normalize import TradesNormalizer
from capitalizator.types import MarketEvent


class BybitTradesWs:
    """Turns already-decoded JSON frames into MarketEvents.

    Opening a live socket is a caller concern (VPS, public endpoint, no keys).
    """

    def __init__(self, normalizer: TradesNormalizer | None = None) -> None:
        self.normalizer = normalizer or TradesNormalizer()
        self.next_seq = 1

    def ingest_frames(
        self,
        frames: Iterable[dict[str, Any]],
        *,
        recv_ts: datetime | None = None,
    ) -> list[MarketEvent]:
        now = recv_ts or datetime.now(tz=UTC)
        out: list[MarketEvent] = []
        for frame in frames:
            batch = self.normalizer.normalize_frame(
                frame, recv_ts=now, seq_start=self.next_seq
            )
            self.next_seq += len(batch)
            out.extend(batch)
        return out
