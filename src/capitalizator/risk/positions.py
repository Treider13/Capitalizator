"""1.5.3 — one open idea. A second entry is reject. No averaging field."""

from __future__ import annotations


class PositionBook:
    def __init__(self) -> None:
        self.open = 0

    def allow_entry(self) -> bool:
        return self.open == 0

    def on_open(self) -> None:
        if self.open >= 1:
            raise ValueError("already in a position")
        self.open = 1

    def on_flat(self) -> None:
        self.open = 0
