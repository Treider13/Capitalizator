"""Three journal pictures. Not a second entry engine.

A — bounce at a pre-drawn zone.
B — breakout with a close beyond + later retest (desk labels the idea).
Г — failed bounce / failed break; always a new card_id.
"""

from __future__ import annotations

from typing import Literal

Picture = Literal["A", "B", "Г"]

IDEA_PICTURE: dict[str, Picture] = {
    "bounce": "A",
    "breakout": "B",
    "failed_break": "Г",
}


def picture_for(idea: str) -> Picture:
    if idea not in IDEA_PICTURE:
        raise ValueError(f"unknown idea: {idea!r}")
    return IDEA_PICTURE[idea]


def needs_new_card(idea: str) -> bool:
    """Picture Г is a new card. A and B may reuse the open card."""
    return picture_for(idea) == "Г"
