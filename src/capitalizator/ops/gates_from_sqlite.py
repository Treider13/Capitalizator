"""Display gates from the knowledge journal. Not a substitute for ops.gates CLI.

Counts come from SQLite. Missing rows stay red. Does not write phase.yaml.
"""

from __future__ import annotations

from typing import Any

from capitalizator.ops.knowledge import Knowledge
from capitalizator.ops.thresholds import load_gates


def gates_from_sqlite(knowledge: Knowledge) -> dict[str, Any]:
    journal = knowledge.journal_rows() if knowledge.available() else []
    episodes = knowledge.episodes() if knowledge.available() else []
    th = load_gates()
    n_touches = len(journal)
    n_shadow = sum(1 for row in journal if row.get("shadow_would"))
    n_skip = sum(1 for row in journal if row.get("skip_reason"))
    n_episodes = len(episodes)
    n_demo_bounce = sum(
        1
        for row in episodes
        if row.get("mode") == "demo" and str(row.get("gesture") or "") != ""
    )
    n_live = sum(1 for row in episodes if row.get("mode") == "live")
    f0 = th["f0"]
    f1 = th["f1"]
    f3 = th["f3"]
    f4 = th["f4"]
    phases = {
        "f0": {
            "ok": False,
            "counts_met": n_touches >= int(f0["touches_min"]),
            "need": int(f0["touches_min"]),
            "have": n_touches,
            "note": "полный F0 — 30 суток ленты, не один счётчик",
        },
        "f1": {
            "ok": n_demo_bounce >= int(f1["n_bounce_demo_min"]),
            "need": int(f1["n_bounce_demo_min"]),
            "have": n_demo_bounce,
        },
        "f2": {
            "ok": False,
            "need": int(th["f2"]["cards_with_outcome_min"]),
            "have": 0,
            "note": "карточки с outcome считаются из ops/gates, не из journal",
        },
        "f3": {
            "ok": False,
            "need": int(f3["n_sum_demo_min"]),
            "have": n_demo_bounce,
        },
        "f4": {
            "ok": n_live >= int(f4["n_live_min"]),
            "need": int(f4["n_live_min"]),
            "have": n_live,
        },
        "f5": {
            "ok": False,
            "need": "ack_f5 + equity_source=main",
            "have": 0,
        },
    }
    return {
        "n_touches": n_touches,
        "n_shadow": n_shadow,
        "n_skip": n_skip,
        "n_episodes": n_episodes,
        "phases": phases,
        "thresholds": {
            "f0_touches_min": int(f0["touches_min"]),
            "f1_n_bounce_demo_min": int(f1["n_bounce_demo_min"]),
            "f3_n_sum_demo_min": int(f3["n_sum_demo_min"]),
            "f4_n_live_min": int(f4["n_live_min"]),
        },
    }
