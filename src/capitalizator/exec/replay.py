"""0.2.7 — replay recorded book frames. No strategy. No invented depth.

ReplayEngine.run(path) -> list[BookCheckpoint]
Two runs of the same file must match best() at every checkpoint.

A gap without a recorded snapshot raises. We do not fetch or invent a book.
Nautilus is not pulled in: bit-identical replay of *our* snapshot+diffs is
the green of this step. Full VPS day stays off-git.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from capitalizator.book.reconstruct import Book
from capitalizator.recorder.book_diff import BookDiffNormalizer


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
