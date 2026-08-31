"""0.4.2 — raw author posts. No weight. No TG.

author_call: author_id, ts, source, text, known_at. weight is rejected.
20+ rows are a human week of legal posts, not a generated list.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from capitalizator.types import require_utc


class AuthorIngestError(ValueError):
    """Author row is missing clocks or carries a weight."""


@dataclass(frozen=True)
class AuthorCall:
    author_id: str
    ts: datetime
    source: str
    text: str
    known_at: datetime
    claims: tuple[str, ...] = ()
    horizon: str | None = None
    resolved_ts: datetime | None = None
    hit: bool | None = None
    r_if_followed: None = None


class AuthorsIngest:
    def __init__(self, rows: Sequence[AuthorCall]) -> None:
        self.rows = list(rows)

    @classmethod
    def from_jsonl(cls, path: Path | str) -> AuthorsIngest:
        rows: list[AuthorCall] = []
        for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip() or line.startswith("#"):
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise AuthorIngestError(f"line {i}: object required")
            if "weight" in raw:
                raise AuthorIngestError(f"line {i}: weight is forbidden until phase 2")
            rows.append(_parse(raw, line=i))
        return cls(rows)

    def visible(self, as_of: datetime) -> list[AuthorCall]:
        when = require_utc(as_of)
        return [r for r in self.rows if r.known_at <= when]


def _parse(raw: dict[str, object], *, line: int) -> AuthorCall:
    author_id = str(raw.get("author_id") or "").strip()
    source = str(raw.get("source") or "").strip()
    text = str(raw.get("text") or "")
    if not author_id or not source:
        raise AuthorIngestError(f"line {line}: author_id and source are required")
    if source.lower() in {"telegram", "tg", "tip"}:
        raise AuthorIngestError(f"line {line}: telegram/tips are forbidden")
    ts = _utc(raw.get("ts"), field="ts", line=line)
    known_at = _utc(raw.get("known_at"), field="known_at", line=line)
    claims_raw = raw.get("claims") or []
    if not isinstance(claims_raw, list):
        raise AuthorIngestError(f"line {line}: claims must be a list")
    horizon = raw.get("horizon")
    return AuthorCall(
        author_id=author_id,
        ts=ts,
        source=source,
        text=text,
        known_at=known_at,
        claims=tuple(str(c) for c in claims_raw),
        horizon=str(horizon) if horizon is not None else None,
    )


def _utc(value: object, *, field: str, line: int) -> datetime:
    if value is None or value == "":
        raise AuthorIngestError(f"line {line}: {field} is required")
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AuthorIngestError(f"line {line}: bad {field}") from exc
    if parsed.tzinfo is None:
        raise AuthorIngestError(f"line {line}: {field} must be UTC")
    return require_utc(parsed)
