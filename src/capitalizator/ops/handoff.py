"""Demo → live: same desk.sqlite. Experience stays. Champion is not promoted.

r_demo is a prior, not a live fill. r_live stays empty until a live episode exists.
Does not send. Does not read keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from capitalizator.ops.knowledge import Knowledge

META_HANDOFF_FROM = "handoff_from"
META_HANDOFF_TOUCHES = "handoff_n_touches"
META_HANDOFF_DEMO = "handoff_n_demo_episodes"
META_HANDOFF_CARDS = "handoff_n_cards"


def experience_snapshot(knowledge: Knowledge) -> dict[str, Any]:
    """Counts already in this vault. Empty is honest zero, not a new book."""
    journal = knowledge.journal_rows() if knowledge.available() else []
    episodes = knowledge.episodes() if knowledge.available() else []
    overlay = knowledge.overlay_rows() if knowledge.available() else []
    n_demo = sum(1 for row in episodes if row.get("mode") == "demo")
    n_live = sum(1 for row in episodes if row.get("mode") == "live")
    n_shadow = sum(1 for row in episodes if row.get("mode") == "shadow")
    return {
        "n_touches": len(journal),
        "n_episodes_demo": n_demo,
        "n_episodes_live": n_live,
        "n_episodes_shadow": n_shadow,
        "n_overlay": len(overlay),
        "n_cards": knowledge.claim_count("b_card:") if knowledge.available() else 0,
        "n_hash": knowledge.counts().get("hash_links", 0) if knowledge.available() else 0,
        "handoff_from": (
            knowledge.meta(META_HANDOFF_FROM) if knowledge.available() else None
        ),
        "handoff_n_touches": (
            knowledge.meta(META_HANDOFF_TOUCHES) if knowledge.available() else None
        ),
        "handoff_n_demo_episodes": (
            knowledge.meta(META_HANDOFF_DEMO) if knowledge.available() else None
        ),
        "handoff_n_cards": (
            knowledge.meta(META_HANDOFF_CARDS) if knowledge.available() else None
        ),
        "same_book": True,
    }


def prior_r(row: Mapping[str, Any]) -> dict[str, str | None]:
    """Live reads demo as prior when r_live is empty. Does not write overlay."""
    for key in ("r_live", "r_demo", "r_shadow"):
        raw = row.get(key)
        if raw not in {None, ""}:
            return {"r": str(raw), "source": key}
    return {"r": None, "source": "none"}


def stamp_demo_to_live(knowledge: Knowledge) -> dict[str, Any]:
    """Record the handoff. Journal, cards, overlay, tape are not deleted."""
    snap = experience_snapshot(knowledge)
    knowledge.set_meta(META_HANDOFF_FROM, "demo")
    knowledge.set_meta(META_HANDOFF_TOUCHES, str(snap["n_touches"]))
    knowledge.set_meta(META_HANDOFF_DEMO, str(snap["n_episodes_demo"]))
    knowledge.set_meta(META_HANDOFF_CARDS, str(snap["n_cards"]))
    out = experience_snapshot(knowledge)
    out["stamped"] = True
    return out
