"""3.14.1 — unlock calendar. Empty is honest. Team today/tomorrow cuts.

PHASE-BUILD CSV. Missing file or header-only → no unlocks, not invented rows.
recipient_type team on this UTC date or the next → screener flag.
Investor/other do not cut. Not a short signal. Does not open size.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.types import require_utc

RECIPIENTS = frozenset({"team", "investor", "other"})
REQUIRED = (
    "unlock_id",
    "symbol",
    "event_time_utc",
    "known_at_utc",
    "recipient_type",
    "amount_tokens",
    "amount_usd_est",
    "source",
)


class UnlockError(ValueError):
    """Unlock row is missing clocks or uses an unknown recipient."""


@dataclass(frozen=True)
class UnlockRow:
    unlock_id: str
    symbol: str
    event_time: datetime
    known_at: datetime
    recipient_type: str
    amount_tokens: Decimal | None
    amount_usd_est: Decimal | None
    source: str


def default_unlocks_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "calendars" / "unlocks.csv"
        if candidate.is_file():
            return candidate
    return Path("infra/calendars/unlocks.csv")


class Unlocks:
    def __init__(self, rows: Sequence[UnlockRow] = ()) -> None:
        self.rows = list(rows)

    @classmethod
    def load(cls, path: Path | str | None = None) -> Unlocks:
        target = Path(path) if path is not None else default_unlocks_path()
        if not target.is_file():
            return cls(())
        return cls.from_csv(target)

    @classmethod
    def from_csv(cls, path: Path | str) -> Unlocks:
        text = Path(path).read_text(encoding="utf-8")
        reader = csv.DictReader(
            line for line in text.splitlines() if line.strip() and not line.startswith("#")
        )
        if reader.fieldnames is None:
            raise UnlockError("csv has no header")
        missing = [k for k in REQUIRED if k not in reader.fieldnames]
        if missing:
            raise UnlockError(f"missing columns: {missing}")
        extra = sorted(set(reader.fieldnames) - set(REQUIRED))
        if extra:
            raise UnlockError(f"unknown columns: {extra}")
        rows = [_parse_row(raw, line=i) for i, raw in enumerate(reader, start=2)]
        return cls(rows)

    def visible(self, as_of: datetime) -> list[UnlockRow]:
        when = require_utc(as_of)
        return [row for row in self.rows if row.known_at <= when]

    def team_today(self, symbol: str, now: datetime) -> bool:
        return self._team_on(symbol, now, days=0)

    def team_tomorrow(self, symbol: str, now: datetime) -> bool:
        return self._team_on(symbol, now, days=1)

    def team_blocks(self, symbol: str, now: datetime) -> bool:
        return self.team_today(symbol, now) or self.team_tomorrow(symbol, now)

    def _team_on(self, symbol: str, now: datetime, *, days: int) -> bool:
        when = require_utc(now)
        target = when.date() + timedelta(days=days)
        for row in self.visible(when):
            if row.symbol != symbol:
                continue
            if row.recipient_type != "team":
                continue
            if require_utc(row.event_time).date() == target:
                return True
        return False


def _parse_row(raw: dict[str, str], *, line: int) -> UnlockRow:
    unlock_id = (raw.get("unlock_id") or "").strip()
    symbol = (raw.get("symbol") or "").strip()
    if not unlock_id or not symbol:
        raise UnlockError(f"line {line}: unlock_id and symbol are required")
    recipient = (raw.get("recipient_type") or "").strip()
    if recipient not in RECIPIENTS:
        raise UnlockError(f"line {line}: unknown recipient_type {recipient!r}")
    return UnlockRow(
        unlock_id=unlock_id,
        symbol=symbol,
        event_time=_utc(raw.get("event_time_utc"), field="event_time_utc", line=line),
        known_at=_utc(raw.get("known_at_utc"), field="known_at_utc", line=line),
        recipient_type=recipient,
        amount_tokens=_opt_dec(raw.get("amount_tokens"), field="amount_tokens", line=line),
        amount_usd_est=_opt_dec(raw.get("amount_usd_est"), field="amount_usd_est", line=line),
        source=(raw.get("source") or "").strip(),
    )


def _opt_dec(value: str | None, *, field: str, line: int) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception as exc:
        raise UnlockError(f"line {line}: bad {field} {value!r}") from exc


def _utc(value: str | None, *, field: str, line: int) -> datetime:
    text = (value or "").strip()
    if not text:
        raise UnlockError(f"line {line}: {field} is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise UnlockError(f"line {line}: bad {field} {value!r}") from exc
    if parsed.tzinfo is None:
        raise UnlockError(f"line {line}: {field} must be UTC (Z)")
    return require_utc(parsed)
