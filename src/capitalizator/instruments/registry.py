"""Instrument registry: tick, qty step, min qty, min notional, leverage, funding.

Source of truth is Bybit `GET /v5/market/instruments-info` (category=linear):
https://bybit-exchange.github.io/docs/v5/market/instrument
Fields used: priceFilter.tickSize, lotSizeFilter.qtyStep / minOrderQty /
minNotionalValue, leverageFilter.maxLeverage, fundingInterval (minutes), status.

Offline the registry reads `infra/instruments.yaml` — a snapshot with a
`fetched_at` stamp. A symbol missing from both sources is `InstrumentUnknown`:
the desk refuses to build zones / size an order for it instead of guessing a tick.
The old global `tick_size=0.1` survives only as `Instrument.fixture(...)` for tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

import yaml

FetchFn = Callable[[], Iterable[Mapping[str, Any]]]


class InstrumentUnknown(KeyError):
    """No instrument facts for this symbol. Do not invent a tick."""


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal
    max_lev: Decimal
    funding_interval_min: int
    status: str
    source: str
    fetched_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("tick", "qty_step", "min_qty"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.min_notional < 0 or self.max_lev <= 0:
            raise ValueError("min_notional >= 0 and max_lev > 0 required")

    @property
    def trading(self) -> bool:
        return self.status == "Trading"

    def round_price(self, px: Decimal) -> Decimal:
        return (px / self.tick).to_integral_value(rounding=ROUND_DOWN) * self.tick

    def round_qty(self, qty: Decimal) -> Decimal:
        return (qty / self.qty_step).to_integral_value(rounding=ROUND_DOWN) * self.qty_step

    def qty_ok(self, qty: Decimal, px: Decimal) -> tuple[bool, str]:
        if qty < self.min_qty:
            return False, f"qty {qty} < minOrderQty {self.min_qty}"
        if qty * px < self.min_notional:
            return False, f"notional {qty * px} < minNotionalValue {self.min_notional}"
        if self.round_qty(qty) != qty:
            return False, f"qty {qty} not on qtyStep {self.qty_step}"
        return True, "ok"

    @classmethod
    def fixture(cls, symbol: str, *, tick: Decimal | str = "0.1") -> Instrument:
        """Test-only instrument with the legacy global tick. Not a market fact."""
        return cls(
            symbol=symbol,
            tick=Decimal(str(tick)),
            qty_step=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            min_notional=Decimal("5"),
            max_lev=Decimal("100"),
            funding_interval_min=480,
            status="Trading",
            source="fixture",
        )


def instrument_from_bybit(row: Mapping[str, Any], *, fetched_at: datetime) -> Instrument:
    """Map one `instruments-info` list item. Unknown shape is an error, not a default."""
    try:
        price = row["priceFilter"]
        lot = row["lotSizeFilter"]
        lev = row.get("leverageFilter") or {}
        return Instrument(
            symbol=str(row["symbol"]),
            tick=Decimal(str(price["tickSize"])),
            qty_step=Decimal(str(lot["qtyStep"])),
            min_qty=Decimal(str(lot["minOrderQty"])),
            min_notional=Decimal(str(lot.get("minNotionalValue") or "0")),
            max_lev=Decimal(str(lev.get("maxLeverage") or "1")),
            funding_interval_min=int(row.get("fundingInterval") or 480),
            status=str(row.get("status") or "unknown"),
            source="bybit",
            fetched_at=fetched_at,
        )
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError(f"bad instruments-info row: {exc}") from exc


def _find_snapshot() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "instruments.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_snapshot(path: Path | None = None) -> dict[str, Instrument]:
    target = path if path is not None else _find_snapshot()
    if target is None or not target.is_file():
        return {}
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("instruments.yaml must be a mapping")
    fetched = raw.get("fetched_at")
    stamp = None
    if fetched:
        stamp = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
    rows = raw.get("instruments") or {}
    out: dict[str, Instrument] = {}
    for symbol, body in rows.items():
        if not isinstance(body, dict):
            raise ValueError(f"instrument {symbol}: body must be a mapping")
        out[str(symbol)] = Instrument(
            symbol=str(symbol),
            tick=Decimal(str(body["tick"])),
            qty_step=Decimal(str(body["qty_step"])),
            min_qty=Decimal(str(body["min_qty"])),
            min_notional=Decimal(str(body.get("min_notional", "0"))),
            max_lev=Decimal(str(body.get("max_lev", "1"))),
            funding_interval_min=int(body.get("funding_interval_min", 480)),
            status=str(body.get("status", "Trading")),
            source=str(body.get("source") or raw.get("source") or "snapshot"),
            fetched_at=stamp,
        )
    return out


class InstrumentRegistry:
    """symbol → Instrument. Fetch is injected; offline falls back to the snapshot."""

    def __init__(
        self,
        instruments: Mapping[str, Instrument] | None = None,
        *,
        fetch: FetchFn | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        self._rows: dict[str, Instrument] = dict(instruments or {})
        self._fetch = fetch
        self._snapshot_path = snapshot_path
        self.last_refresh: datetime | None = None
        self.last_error: str | None = None

    @classmethod
    def offline(cls, path: Path | None = None) -> InstrumentRegistry:
        return cls(load_snapshot(path), snapshot_path=path)

    def refresh(self, *, now: datetime | None = None) -> int:
        """Pull from the injected fetch. Returns rows updated; keeps old rows on error."""
        if self._fetch is None:
            return 0
        when = now if now is not None else datetime.now(tz=UTC)
        try:
            rows = list(self._fetch())
        except Exception as exc:  # network / auth / shape — keep the snapshot, remember why
            self.last_error = str(exc)
            return 0
        n = 0
        for row in rows:
            inst = instrument_from_bybit(row, fetched_at=when)
            self._rows[inst.symbol] = inst
            n += 1
        self.last_refresh = when
        self.last_error = None
        return n

    def get(self, symbol: str) -> Instrument:
        try:
            return self._rows[symbol]
        except KeyError as exc:
            raise InstrumentUnknown(symbol) from exc

    def has(self, symbol: str) -> bool:
        return symbol in self._rows

    def tick(self, symbol: str) -> Decimal:
        return self.get(symbol).tick

    def put(self, inst: Instrument) -> None:
        self._rows[inst.symbol] = inst

    def symbols(self) -> list[str]:
        return sorted(self._rows)

    def to_snapshot(self) -> dict[str, Any]:
        stamp = self.last_refresh or max(
            (r.fetched_at for r in self._rows.values() if r.fetched_at), default=None
        )
        return {
            "source": "bybit instruments-info (category=linear)",
            "fetched_at": stamp.isoformat() if stamp else None,
            "instruments": {
                s: {
                    "tick": str(r.tick),
                    "qty_step": str(r.qty_step),
                    "min_qty": str(r.min_qty),
                    "min_notional": str(r.min_notional),
                    "max_lev": str(r.max_lev),
                    "funding_interval_min": r.funding_interval_min,
                    "status": r.status,
                    "source": r.source,
                }
                for s, r in sorted(self._rows.items())
            },
        }
