"""Passport — what is *normal* for this symbol. Median / MAD over a bounded window.

ОКО adapts to any market by reading nothing in absolute units. A 50 BTC wall is
loud on one book and noise on another; the Passport says which. Same law as
PRS: robust z needs ≥30 observations (Y_MIN_N); before that every normalised
feature is None — not a guess.

Observations are appended *after* the frame that used them, so a touch is
always judged by the past only (PIT).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

MATURE_N = 30
WINDOW = 400
MAD_TO_SIGMA = Decimal("1.4826")
EPS = Decimal("1e-9")

FIELDS = ("depth", "spread_ticks", "print_qty", "prints_per_s", "range_ticks")


class RobustStat:
    """Bounded deque; median and MAD are recomputed on demand. Deterministic."""

    def __init__(self, values: Iterable[Decimal] = (), *, window: int = WINDOW) -> None:
        if window < MATURE_N:
            raise ValueError("window must be >= MATURE_N")
        self.values: deque[Decimal] = deque(maxlen=window)
        for value in values:
            self.add(value)

    def add(self, value: Decimal) -> None:
        if not isinstance(value, Decimal):
            raise TypeError("RobustStat takes Decimal")
        if not value.is_finite():
            raise ValueError("RobustStat takes finite values")
        self.values.append(value)

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def mature(self) -> bool:
        return self.n >= MATURE_N

    def median(self) -> Decimal | None:
        if not self.mature:
            return None
        return _median(sorted(self.values))

    def mad(self) -> Decimal | None:
        med = self.median()
        if med is None:
            return None
        return _median(sorted(abs(v - med) for v in self.values))

    def z(self, value: Decimal) -> Decimal | None:
        """Robust z: (x − median) / (1.4826·MAD). None before maturity."""
        med = self.median()
        mad = self.mad()
        if med is None or mad is None:
            return None
        scale = mad * MAD_TO_SIGMA
        return (value - med) / (scale if scale > 0 else EPS)

    def rel(self, value: Decimal) -> Decimal | None:
        """x / median. None before maturity or when the median is not positive."""
        med = self.median()
        if med is None or med <= 0:
            return None
        return value / med

    def to_list(self) -> list[str]:
        return [format(v, "f") for v in self.values]

    @classmethod
    def from_list(cls, raw: Iterable[Any], *, window: int = WINDOW) -> RobustStat:
        out = cls(window=window)
        for item in raw:
            try:
                out.add(Decimal(str(item)))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(f"bad passport value: {item!r}") from exc
        return out


class Passport:
    """Five robust stats per symbol. Mature when every stat has ≥30 observations."""

    def __init__(self, symbol: str) -> None:
        if not symbol:
            raise ValueError("passport needs a symbol")
        self.symbol = symbol
        self.depth = RobustStat()
        self.spread_ticks = RobustStat()
        self.print_qty = RobustStat()
        self.prints_per_s = RobustStat()
        self.range_ticks = RobustStat()

    def stats(self) -> dict[str, RobustStat]:
        return {name: getattr(self, name) for name in FIELDS}

    @property
    def n(self) -> int:
        return min(stat.n for stat in self.stats().values())

    @property
    def mature(self) -> bool:
        return all(stat.mature for stat in self.stats().values())

    def observe(
        self,
        *,
        depth: Decimal,
        spread_ticks: Decimal | None,
        print_qtys: Iterable[Decimal],
        prints_per_s: Decimal,
        range_ticks: Decimal | None,
    ) -> None:
        """One touch window → one observation per stat (prints: one per print).

        A window without a spread or without ≥2 prints leaves that stat alone.
        The Passport never stores a 0 invented for a missing fact.
        """
        if depth < 0 or prints_per_s < 0:
            raise ValueError("depth and prints_per_s must be >= 0")
        self.depth.add(depth)
        if spread_ticks is not None:
            if spread_ticks < 0:
                raise ValueError("spread_ticks must be >= 0")
            self.spread_ticks.add(spread_ticks)
        for qty in print_qtys:
            if qty <= 0:
                raise ValueError("print qty must be > 0")
            self.print_qty.add(qty)
        self.prints_per_s.add(prints_per_s)
        if range_ticks is not None:
            if range_ticks < 0:
                raise ValueError("range_ticks must be >= 0")
            self.range_ticks.add(range_ticks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            **{name: stat.to_list() for name, stat in self.stats().items()},
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Passport:
        symbol = str(raw.get("symbol") or "")
        out = cls(symbol)
        for name in FIELDS:
            values = raw.get(name)
            if values is None:
                continue
            if not isinstance(values, list):
                raise ValueError(f"passport {name} must be a list")
            setattr(out, name, RobustStat.from_list(values))
        return out


def _median(ordered: list[Decimal]) -> Decimal:
    n = len(ordered)
    if n == 0:
        raise ValueError("median of empty list")
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
