"""1.8.2 — paper slip table. Empty median is None, not a fake zero."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TcaRow:
    model_px: Decimal
    fill_px: Decimal
    delay_s: Decimal
    tick: Decimal

    def __post_init__(self) -> None:
        if self.tick <= 0:
            raise ValueError("tick must be > 0")
        if self.delay_s < 0:
            raise ValueError("delay_s must be >= 0")

    @property
    def slip_ticks(self) -> Decimal:
        return (self.fill_px - self.model_px) / self.tick


class TcaTable:
    def __init__(self) -> None:
        self.rows: list[TcaRow] = []

    def add(self, row: TcaRow) -> None:
        self.rows.append(row)

    def median_slip_ticks(self) -> Decimal | None:
        if not self.rows:
            return None
        slips = sorted(abs(row.slip_ticks) for row in self.rows)
        mid = len(slips) // 2
        if len(slips) % 2 == 1:
            return slips[mid]
        return (slips[mid - 1] + slips[mid]) / 2
