"""3.14.2 — class × regime prior. Empty is honest. n<5 is not our edge.

PHASE-BUILD: intelligence-layer numbers are a prior, not truth.
Our n ≥ 5 would replace a prior. This file does not copy blog coefficients.
Does not open size. Missing file → no rows.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REQUIRED = (
    "class",
    "regime",
    "horizon_min",
    "mean_ret",
    "n",
    "source",
)
N_OURS = 5


class ReactionError(ValueError):
    """Reaction row is missing columns or has a bad n."""


@dataclass(frozen=True)
class ReactionRow:
    event_class: str
    regime: str
    horizon_min: int
    mean_ret: Decimal
    n: int
    source: str


def default_reaction_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "calendars" / "reaction_prior.csv"
        if candidate.is_file():
            return candidate
    return Path("infra/calendars/reaction_prior.csv")


class ReactionTable:
    def __init__(self, rows: Sequence[ReactionRow] = ()) -> None:
        self.rows = list(rows)

    @classmethod
    def load(cls, path: Path | str | None = None) -> ReactionTable:
        target = Path(path) if path is not None else default_reaction_path()
        if not target.is_file():
            return cls(())
        return cls.from_csv(target)

    @classmethod
    def from_csv(cls, path: Path | str) -> ReactionTable:
        text = Path(path).read_text(encoding="utf-8")
        reader = csv.DictReader(
            line for line in text.splitlines() if line.strip() and not line.startswith("#")
        )
        if reader.fieldnames is None:
            raise ReactionError("csv has no header")
        missing = [k for k in REQUIRED if k not in reader.fieldnames]
        if missing:
            raise ReactionError(f"missing columns: {missing}")
        extra = sorted(set(reader.fieldnames) - set(REQUIRED))
        if extra:
            raise ReactionError(f"unknown columns: {extra}")
        rows = [_parse(raw, line=i) for i, raw in enumerate(reader, start=2)]
        return cls(rows)

    def our_coef(self, event_class: str, regime: str) -> Decimal | None:
        hit = [
            row
            for row in self.rows
            if row.event_class == event_class and row.regime == regime and row.n >= N_OURS
        ]
        if not hit:
            return None
        return hit[0].mean_ret

    def opens_size(self) -> bool:
        return False


def _parse(raw: dict[str, str], *, line: int) -> ReactionRow:
    klass = (raw.get("class") or "").strip()
    regime = (raw.get("regime") or "").strip()
    if not klass or not regime:
        raise ReactionError(f"line {line}: class and regime are required")
    try:
        n = int((raw.get("n") or "").strip())
        horizon = int((raw.get("horizon_min") or "").strip())
        mean_ret = Decimal((raw.get("mean_ret") or "").strip())
    except Exception as exc:
        raise ReactionError(f"line {line}: bad n/horizon/mean_ret") from exc
    if n < 0 or horizon <= 0:
        raise ReactionError(f"line {line}: n must be >= 0 and horizon_min > 0")
    return ReactionRow(
        event_class=klass,
        regime=regime,
        horizon_min=horizon,
        mean_ret=mean_ret,
        n=n,
        source=(raw.get("source") or "").strip(),
    )
