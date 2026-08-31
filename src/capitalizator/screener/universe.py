"""Week-0 universe file. BTC+ETH only until 0.1.7. No 200-coin dump.

Canonical shape (PHASE-BUILD):
    exchange: bybit
    category: linear
    symbols: [BTCUSDT, ETHUSDT]
    # 8–15 альтов добавить после 0.1.7

This module validates that shape. It does not measure spread/volume.
It does not mark 0.2.6 live-green.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
MAX_SYMBOLS = 15
SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
FORBIDDEN_EXCHANGES = frozenset({"htx", "huobi"})


class UniverseError(ValueError):
    """Universe file is not a legal week-0 list."""


@dataclass(frozen=True)
class Universe:
    exchange: str
    category: str
    symbols: tuple[str, ...]


def validate_universe(raw: Any) -> Universe:
    if not isinstance(raw, dict):
        raise UniverseError("universe must be a mapping")
    exchange = str(raw.get("exchange") or "").strip().lower()
    if not exchange:
        raise UniverseError("exchange is required")
    if exchange in FORBIDDEN_EXCHANGES:
        raise UniverseError("HTX/Huobi is forbidden")
    if exchange != "bybit":
        raise UniverseError("week0 exchange must be bybit")
    category = str(raw.get("category") or "").strip().lower()
    if category != "linear":
        raise UniverseError("week0 category must be linear")
    symbols = raw.get("symbols")
    if not isinstance(symbols, list):
        raise UniverseError("symbols must be a list")
    names = [str(s).strip() for s in symbols]
    if any(not n for n in names):
        raise UniverseError("empty symbol")
    if len(names) > 200 or len(names) > MAX_SYMBOLS:
        raise UniverseError(
            f"reject wide universe: {len(names)} symbols (max {MAX_SYMBOLS}, never 200)"
        )
    missing = [s for s in REQUIRED_SYMBOLS if s not in names]
    if missing:
        raise UniverseError(f"required symbols missing: {missing}")
    if len(set(names)) != len(names):
        raise UniverseError("duplicate symbols")
    for name in names:
        if not SYMBOL_RE.fullmatch(name):
            raise UniverseError(f"not a linear USDT perp name: {name}")
    return Universe(exchange=exchange, category=category, symbols=tuple(names))


def load_universe(path: Path) -> Universe:
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return validate_universe(raw)


def default_week0_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "universe.week0.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/universe.week0.yaml not found from package tree")
