"""Call the paper modules that must not stay unwired. They do not open size.

Reaction / whale pit / jury weight / ОКО eyelid / nmin F1 all refuse to open.
The desk journals the facts so the operator sees they ran.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from capitalizator.jury.weights import weight_opens_size
from capitalizator.news_macro.reaction import ReactionTable
from capitalizator.oko.eyelid import oko_opens_size
from capitalizator.risk.nmin import size_mult as nmin_size
from capitalizator.whales.pit import WhalePit


def snapshot(*, n_zlg: int = 0, gesture: str | None = None) -> dict[str, Any]:
    return {
        "reaction_opens": ReactionTable().opens_size(),
        "pit_accepts": WhalePit().accept(),
        "weight_opens": weight_opens_size(Decimal("1")),
        "oko_opens": oko_opens_size(None),
        "nmin_mult": str(nmin_size(n=n_zlg, gesture=gesture, phase="f1")),
    }
