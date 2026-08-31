"""1.7.1 — CardDraft schema. Missing file + require_card → reject.

Claims are whatever the operator wrote. This module does not invent
'23 of 31' and does not mark VERIFIED.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from capitalizator.types import require_utc

Verdict = Literal["pending", "VERIFIED", "REFUTED", "UNVERIFIABLE"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    subject: str
    value: str
    as_of: datetime
    known_at: datetime
    horizon: str
    load_bearing: bool
    verdict: Verdict = "pending"

    @field_validator("as_of", "known_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class CardDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thesis: str
    claims: list[Claim] = Field(min_length=5, max_length=7)

    @field_validator("thesis")
    @classmethod
    def _thesis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("thesis is empty")
        return value


def require_card(path: Path | str | None, *, required: bool) -> CardDraft | None:
    if not required:
        return None
    if path is None:
        raise ValueError("card required")
    file = Path(path)
    if not file.is_file():
        raise ValueError("card required")
    return CardDraft.model_validate_json(file.read_text(encoding="utf-8"))


def load_bearing_ok(card: CardDraft) -> bool:
    """At least one load-bearing claim, and every one of them is VERIFIED."""
    bearing = [c for c in card.claims if c.load_bearing]
    if not bearing:
        return False
    return all(c.verdict == "VERIFIED" for c in bearing)
