"""One idea per correlation group (sessions release, max_open_positions > 1).

Static groups come from `infra/corr_groups.yaml`; dynamic pairs come from the
Pearson correlation of hourly close-to-close returns over a rolling window (30 days
of 1h bars = 720 returns, minimum 48 to say anything). Two symbols are "correlated"
when they share a static group OR |ρ| ≥ threshold on ≥ 48 aligned returns.

The rule is symmetric: a second idea on a correlated symbol is refused whatever
its side — same side is the same bet twice, opposite side is a hedge, and the desk
trades theses, not hedges. Unknown correlation (too few bars) is not a block; the
static groups are the floor that works with no bars at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

GROUPS_KEYS = frozenset({"groups"})
MIN_ALIGNED_RETURNS = 48


class CorrGroupsError(ValueError):
    """corr_groups.yaml is not a legal grouping."""


def _find_yaml() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "corr_groups.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/corr_groups.yaml missing")


def load_groups(path: Path | None = None) -> dict[str, str]:
    """symbol → group name. A symbol in two groups is an error."""
    target = path if path is not None else _find_yaml()
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise CorrGroupsError("corr_groups.yaml must be a mapping")
    extra = set(raw) - GROUPS_KEYS
    if extra:
        raise CorrGroupsError(f"unknown keys {sorted(extra)}")
    groups = raw.get("groups")
    if not isinstance(groups, Mapping) or not groups:
        raise CorrGroupsError("groups must be a non-empty mapping")
    out: dict[str, str] = {}
    for name, members in groups.items():
        if not isinstance(members, list) or not members:
            raise CorrGroupsError(f"group {name!r} must be a non-empty list")
        for sym in members:
            s = str(sym)
            if s in out:
                raise CorrGroupsError(f"{s} is in two groups: {out[s]} and {name}")
            out[s] = str(name)
    return out


def pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    """Pearson ρ on aligned samples; None when fewer than MIN_ALIGNED_RETURNS or flat."""
    n = min(len(xs), len(ys))
    if n < MIN_ALIGNED_RETURNS:
        return None
    xs = xs[-n:]
    ys = ys[-n:]
    mx = sum(xs, Decimal(0)) / n
    my = sum(ys, Decimal(0)) / n
    sxy = sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)), Decimal(0))
    sxx = sum(((x - mx) ** 2 for x in xs), Decimal(0))
    syy = sum(((y - my) ** 2 for y in ys), Decimal(0))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx.sqrt() * syy.sqrt())


def returns_from_closes(closes: Sequence[tuple[Any, Decimal]]) -> dict[Any, Decimal]:
    """(bar_close_ts, close) rows → {close_ts: log-free simple return vs previous close}."""
    out: dict[Any, Decimal] = {}
    prev: Decimal | None = None
    for ts, px in closes:
        if prev is not None and prev > 0 and px > 0:
            out[ts] = px / prev - 1
        prev = px
    return out


def aligned(
    a: Mapping[Any, Decimal], b: Mapping[Any, Decimal]
) -> tuple[list[Decimal], list[Decimal]]:
    keys = sorted(set(a) & set(b))
    return [a[k] for k in keys], [b[k] for k in keys]


@dataclass
class CorrelationGuard:
    """Static groups + a rolling correlation matrix the desk refreshes daily."""

    groups: Mapping[str, str]
    threshold: Decimal
    rho: dict[frozenset[str], Decimal]

    @classmethod
    def load(cls, *, threshold: Decimal, path: Path | None = None) -> CorrelationGuard:
        if not (Decimal(0) < threshold <= Decimal(1)):
            raise ValueError("threshold must be in (0, 1]")
        return cls(groups=load_groups(path), threshold=threshold, rho={})

    def group_of(self, symbol: str) -> str:
        return self.groups.get(symbol, symbol)

    def refresh(self, returns: Mapping[str, Mapping[Any, Decimal]]) -> int:
        """Recompute ρ for every symbol pair from per-symbol return series. Returns pairs set."""
        fresh: dict[frozenset[str], Decimal] = {}
        symbols = sorted(returns)
        for i, a in enumerate(symbols):
            for b in symbols[i + 1 :]:
                xs, ys = aligned(returns[a], returns[b])
                r = pearson(xs, ys)
                if r is not None:
                    fresh[frozenset((a, b))] = r
        self.rho = fresh
        return len(fresh)

    def correlated(self, a: str, b: str) -> tuple[bool, str]:
        if a == b:
            return True, "same_symbol"
        if self.group_of(a) == self.group_of(b):
            return True, f"group:{self.group_of(a)}"
        r = self.rho.get(frozenset((a, b)))
        if r is not None and abs(r) >= self.threshold:
            return True, f"rho:{r.quantize(Decimal('0.01'))}"
        return False, "independent"

    def blocks(self, symbol: str, open_symbols: Iterable[str]) -> tuple[bool, str]:
        """True with the reason when any open idea is correlated with `symbol`."""
        for other in open_symbols:
            hit, why = self.correlated(symbol, other)
            if hit:
                return True, f"corr:{other}:{why}"
        return False, "ok"
