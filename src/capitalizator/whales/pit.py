"""3.15.1 paper — a sighting has known_at. Missing file is empty, not a wallet.

Does not scrape Hyperliquid. Does not accept an entry. known_at is when *we* saw it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from capitalizator.types import require_utc


class WhalePitError(ValueError):
    """Sighting is missing a clock or carries a signal field."""


@dataclass(frozen=True)
class Sighting:
    address: str
    known_at: datetime
    source: str


class WhalePit:
    def __init__(self, rows: Sequence[Sighting] = ()) -> None:
        self.rows = list(rows)

    @classmethod
    def load(cls, path: Path | str | None = None) -> WhalePit:
        if path is None:
            return cls(())
        target = Path(path)
        if not target.is_file():
            return cls(())
        rows: list[Sighting] = []
        for i, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip() or line.startswith("#"):
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise WhalePitError(f"line {i}: object required")
            if "signal" in raw or "weight" in raw or "side" in raw:
                raise WhalePitError(f"line {i}: signal/weight/side are forbidden")
            rows.append(_parse(raw, line=i))
        return cls(rows)

    def visible(self, as_of: datetime) -> list[Sighting]:
        when = require_utc(as_of)
        return [r for r in self.rows if r.known_at <= when]

    def accept(self) -> bool:
        return False


def _parse(raw: dict[str, object], *, line: int) -> Sighting:
    address = str(raw.get("address") or "").strip()
    source = str(raw.get("source") or "").strip()
    if not address or not source:
        raise WhalePitError(f"line {line}: address and source are required")
    return Sighting(address=address, known_at=_utc(raw.get("known_at"), line=line), source=source)


def _utc(value: object, *, line: int) -> datetime:
    if value is None or value == "":
        raise WhalePitError(f"line {line}: known_at is required")
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise WhalePitError(f"line {line}: known_at must be UTC")
    return require_utc(parsed)
