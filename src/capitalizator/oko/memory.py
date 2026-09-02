"""Immune Memory — ОКО remembers the shape of the trap, not the price.

Every resolved touch leaves an antigen: the Shadow + Footprint fingerprint
(10 + 3 ints), the idea, and whether the outcome went *against* the idea
(trap). A new window is matched
to antigens within Hamming distance ≤ 1 of the same idea family. If ≥20 such
episodes exist and the Wilson 95% lower bound of the trap rate is above 0.5,
the pattern is *recognised* — the Eyelid vetoes. Below 20 the memory is an
observer: it writes, it does not vote. `die` teaches nothing and is not stored.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from capitalizator.oko.footprint import FINGERPRINT_LEN
from capitalizator.types import require_utc

N_MIN = 20
MAX_DISTANCE = 1
MAX_RECORDS = 5000
Z_95 = 1.959963984540054
TRAP_LOWER_BOUND = 0.5
IDEA_FAMILY = {"bounce": "bounce", "failed_break": "bounce", "breakout": "break"}


@dataclass(frozen=True)
class Antigen:
    fingerprint: tuple[int, ...]
    family: str
    trap: bool
    ts: str

    def __post_init__(self) -> None:
        if len(self.fingerprint) != FINGERPRINT_LEN:
            raise ValueError("fingerprint length")
        if self.family not in {"bounce", "break"}:
            raise ValueError("family must be bounce|break")


@dataclass(frozen=True)
class Recognition:
    n: int
    traps: int
    trap_rate: float | None
    lower_bound: float | None
    recognised: bool


def needed_outcome(idea: str) -> str:
    if idea not in IDEA_FAMILY:
        raise ValueError("idea must be bounce|breakout|failed_break")
    return IDEA_FAMILY[idea]


def is_trap(*, idea: str, outcome: str) -> bool | None:
    """True when the outcome is the opposite of what the idea needed. die → None."""
    need = needed_outcome(idea)
    if outcome == "die":
        return None
    if outcome not in {"bounce", "break"}:
        raise ValueError(f"unknown outcome: {outcome!r}")
    return outcome != need


def wilson_lower(k: int, n: int, *, z: float = Z_95) -> float:
    if n <= 0 or k < 0 or k > n:
        raise ValueError("wilson needs 0 <= k <= n, n > 0")
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    adj = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - adj) / denom)


def hamming(a: Sequence[int], b: Sequence[int]) -> int:
    if len(a) != len(b):
        raise ValueError("fingerprints differ in length")
    return sum(1 for x, y in zip(a, b, strict=True) if x != y)


class ImmuneMemory:
    def __init__(self, symbol: str, *, max_records: int = MAX_RECORDS) -> None:
        if not symbol:
            raise ValueError("memory needs a symbol")
        if max_records < N_MIN:
            raise ValueError("max_records must be >= N_MIN")
        self.symbol = symbol
        self.records: deque[Antigen] = deque(maxlen=max_records)

    @property
    def n(self) -> int:
        return len(self.records)

    def learn(
        self, fingerprint: Sequence[int], *, idea: str, outcome: str, ts: datetime
    ) -> Antigen | None:
        trap = is_trap(idea=idea, outcome=outcome)
        if trap is None:
            return None
        row = Antigen(
            fingerprint=tuple(int(v) for v in fingerprint),
            family=needed_outcome(idea),
            trap=trap,
            ts=require_utc(ts).isoformat(),
        )
        self.records.append(row)
        return row

    def recognise(self, fingerprint: Sequence[int], *, idea: str) -> Recognition:
        family = needed_outcome(idea)
        probe = tuple(int(v) for v in fingerprint)
        if len(probe) != FINGERPRINT_LEN:
            raise ValueError("fingerprint length")
        near = [
            r
            for r in self.records
            if r.family == family and hamming(r.fingerprint, probe) <= MAX_DISTANCE
        ]
        n = len(near)
        traps = sum(1 for r in near if r.trap)
        if n == 0:
            return Recognition(n=0, traps=0, trap_rate=None, lower_bound=None, recognised=False)
        lb = wilson_lower(traps, n)
        return Recognition(
            n=n,
            traps=traps,
            trap_rate=traps / n,
            lower_bound=lb,
            recognised=n >= N_MIN and lb > TRAP_LOWER_BOUND,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "records": [
                {"f": list(r.fingerprint), "family": r.family, "trap": r.trap, "ts": r.ts}
                for r in self.records
            ],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ImmuneMemory:
        out = cls(str(raw.get("symbol") or ""))
        rows = raw.get("records") or []
        if not isinstance(rows, list):
            raise ValueError("memory records must be a list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("memory record must be a mapping")
            out.records.append(
                Antigen(
                    fingerprint=tuple(int(v) for v in row["f"]),
                    family=str(row["family"]),
                    trap=bool(row["trap"]),
                    ts=str(row["ts"]),
                )
            )
        return out
