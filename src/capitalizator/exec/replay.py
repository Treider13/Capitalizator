"""0.2.7 — replay recorded book frames. No strategy. No invented depth.

ReplayEngine.run(path) -> list[BookCheckpoint]
Two runs of the same file must match best() at every checkpoint.

A gap without a recorded snapshot raises. We do not fetch or invent a book.
Nautilus is not pulled in: bit-identical replay of *our* snapshot+diffs is
the green of this step. Full VPS day stays off-git.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from capitalizator.book.reconstruct import Book
from capitalizator.recorder.book_diff import BookDiffNormalizer
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.recorder.ws_trades import BybitTradesWs
from capitalizator.types import MarketEvent, require_utc


@dataclass(frozen=True)
class BookCheckpoint:
    seq: int | None
    best_bid: Decimal | None
    best_ask: Decimal | None

    def best(self) -> tuple[Decimal | None, Decimal | None]:
        return self.best_bid, self.best_ask


class ReplayEngine:
    def run(self, path: Path) -> list[BookCheckpoint]:
        frames = _load_book_frames(path)
        book = Book()
        normalizer = BookDiffNormalizer()
        checkpoints: list[BookCheckpoint] = []
        for frame in frames:
            kind, snap = normalizer.parse_frame(frame)
            if kind == "snapshot":
                book.apply_snapshot(snap)
            else:
                book.apply_diff(snap.bids, snap.asks, seq=snap.seq)
            bid, ask = book.best()
            checkpoints.append(BookCheckpoint(seq=book.seq, best_bid=bid, best_ask=ask))
        return checkpoints

    def run_events(self, events: Sequence[MarketEvent]) -> list[BookCheckpoint]:
        """Same reconstruct as `run`, from already-normalized tape events.

        snapshot + book_diff only. Other streams are skipped. Empty → [].
        A gap still raises — we do not invent a book.
        """
        book = Book()
        checkpoints: list[BookCheckpoint] = []
        for event in events:
            if event.stream == "snapshot":
                book.apply_snapshot(_event_snapshot(event))
            elif event.stream == "book_diff":
                snap = _event_snapshot(event)
                book.apply_diff(snap.bids, snap.asks, seq=snap.seq)
            else:
                continue
            bid, ask = book.best()
            checkpoints.append(BookCheckpoint(seq=book.seq, best_bid=bid, best_ask=ask))
        return checkpoints

    def tape(self, path: Path, *, recv_ts: datetime) -> list[MarketEvent]:
        """Replay recorded prints. Missing trades.jsonl → empty, not invented."""
        frames = _load_trade_frames(path)
        if not frames:
            return []
        return BybitTradesWs().run(frames, recv_ts=require_utc(recv_ts))


def _event_snapshot(event: MarketEvent) -> BookSnapshot:
    seq = event.seq if event.seq is not None else event.payload.get("u")
    if seq is None:
        raise ValueError("book event needs seq")
    return BookSnapshot(
        symbol=event.symbol,
        exchange_ts=event.exchange_ts,
        seq=int(seq),
        bids=_levels(event.payload.get("bids") or event.payload.get("b") or []),
        asks=_levels(event.payload.get("asks") or event.payload.get("a") or []),
    )


def _levels(rows: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(rows, list | tuple):
        return ()
    out: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        out.append((str(row[0]), str(row[1])))
    return tuple(out)


def _load_book_frames(path: Path) -> list[dict[str, Any]]:
    book_path = path / "book.jsonl" if path.is_dir() else path
    lines = book_path.read_text(encoding="utf-8").splitlines()
    frames: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("book jsonl line must be an object")
        frames.append(raw)
    if not frames:
        raise ValueError(f"no book frames in {book_path}")
    return frames


def _load_trade_frames(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir():
        return []
    trade_path = path / "trades.jsonl"
    if not trade_path.is_file():
        return []
    frames: list[dict[str, Any]] = []
    for line in trade_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("trade jsonl line must be an object")
        frames.append(raw)
    return frames
