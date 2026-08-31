"""2.12.1 — a row is parsed only if claims + horizon + known_at already exist.

Does not invent claims from free text. Does not run an LLM.
Does not write 50 posts. Empty journal stays empty.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from capitalizator.authors.ingest import AuthorCall, AuthorsIngest
from capitalizator.card.first_fact import horizon_seconds


class AuthorParseError(ValueError):
    """Horizon is present but not Ns|Nm|Nh|Nd."""


@dataclass(frozen=True)
class ParsedCall:
    author_id: str
    ts: datetime
    source: str
    claims: tuple[str, ...]
    horizon: str
    known_at: datetime


class AuthorParse:
    def parse(self, call: AuthorCall) -> ParsedCall | None:
        if not call.claims:
            return None
        if not call.horizon:
            return None
        try:
            horizon_seconds(call.horizon)
        except ValueError as exc:
            raise AuthorParseError(f"bad horizon {call.horizon!r}") from exc
        return ParsedCall(
            author_id=call.author_id,
            ts=call.ts,
            source=call.source,
            claims=call.claims,
            horizon=call.horizon,
            known_at=call.known_at,
        )

    def from_calls(self, rows: Sequence[AuthorCall]) -> list[ParsedCall]:
        out: list[ParsedCall] = []
        for row in rows:
            got = self.parse(row)
            if got is not None:
                out.append(got)
        return out

    def from_jsonl(self, path: Path | str) -> list[ParsedCall]:
        return self.from_calls(AuthorsIngest.from_jsonl(path).rows)
