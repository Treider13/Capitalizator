"""1.6.4 — spread + maker round-trip must be smaller than the typical move.

Typical move is passed in (ATR, or median bounce if the caller already has n≥20).
This module does not invent ATR from empty history. Unlock today/tomorrow are
flags from the calendar reader, not scraped Tokenomist rows.
"""

from __future__ import annotations

from decimal import Decimal

from capitalizator.screener.universe import Universe, default_week0_path, load_universe


class Screener:
    def __init__(self, universe: Universe | None = None) -> None:
        from capitalizator.exec.fees import FeeTable

        self.universe = universe or load_universe(default_week0_path())
        self.fees = FeeTable()

    def ok(
        self,
        symbol: str,
        *,
        spread_frac: Decimal,
        typical_move: Decimal,
        unlock_tomorrow: bool = False,
        unlock_today: bool = False,
    ) -> bool:
        if symbol not in self.universe.symbols:
            return False
        if unlock_tomorrow or unlock_today:
            return False
        if spread_frac < 0 or typical_move <= 0:
            return False
        cost = spread_frac + self.fees.rate("maker") * 2
        return cost < typical_move
