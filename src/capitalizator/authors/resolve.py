"""2.12.2 — hit/miss after the horizon. The rule is passed in, not rewritten after.

Does not invent a price. Does not set weight. Does not open size.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from capitalizator.authors.ingest import AuthorCall
from capitalizator.card.first_fact import horizon_seconds
from capitalizator.types import require_utc

Direction = Literal["up", "down"]


@dataclass(frozen=True)
class ResolveRule:
    direction: Direction
    threshold_pct: Decimal

    def __post_init__(self) -> None:
        if self.threshold_pct <= 0:
            raise ValueError("threshold_pct must be > 0")


class AuthorsResolve:
    def close(
        self,
        call: AuthorCall,
        *,
        now: datetime,
        ref_px: Decimal,
        close_px: Decimal,
        rule: ResolveRule,
    ) -> AuthorCall:
        if call.hit is not None:
            raise ValueError("cannot change a resolution after the fact")
        if call.horizon is None:
            raise ValueError("horizon required to resolve")
        when = require_utc(now)
        if ref_px <= 0 or close_px <= 0:
            raise ValueError("prices must be > 0")
        due = call.ts + timedelta(seconds=horizon_seconds(call.horizon))
        if when < due:
            return call
        move = (close_px - ref_px) / ref_px
        if rule.direction == "up":
            hit = move >= rule.threshold_pct
        else:
            hit = move <= -rule.threshold_pct
        return replace(call, hit=hit, resolved_ts=when)
