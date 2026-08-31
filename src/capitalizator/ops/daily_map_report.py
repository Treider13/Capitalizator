"""0.3.8 — evening map. Touches, gestures, gaps, ping. No advice.

Forbidden in the generated text: лонг, шорт, купи, продай, завтра.
Zone prices are numbers, not a quote that may carry those tokens.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from capitalizator.memory.registry import Touch
from capitalizator.zones.model import Zone

_ADVICE = re.compile(r"лонг|шорт|купи|продай|завтра", re.IGNORECASE)


def _touches_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "касание"
    if 2 <= n % 10 <= 4 and n % 100 not in {12, 13, 14}:
        return "касания"
    return "касаний"


@dataclass(frozen=True)
class GapRow:
    symbol: str
    stream: str
    n: int


def daily_map_report(
    *,
    day: str,
    rows: Sequence[tuple[Zone, Touch]],
    gaps: Sequence[GapRow] = (),
    ping_ms: float | None = None,
) -> str:
    by_zone: dict[str, list[tuple[Zone, Touch]]] = defaultdict(list)
    for zone, touch in rows:
        by_zone[zone.zone_id].append((zone, touch))
    lines = [f"# Карта {day}", ""]
    if not rows:
        lines.append("Касаний нет.")
    for zone_id, group in by_zone.items():
        zone = group[0][0]
        n = len(group)
        eaten_n = sum(1 for _, t in group if t.tape_eaten is True)
        gestures = [t.gesture for _, t in group if t.gesture]
        gesture_bit = f"; жест {gestures[-1]}" if gestures else ""
        eaten_bit = f"; eaten {eaten_n}" if eaten_n else ""
        lines.append(
            f"{zone.symbol} {zone.lo}–{zone.hi} — {n} {_touches_word(n)}{eaten_bit}{gesture_bit}."
        )
    lines.append("")
    if gaps:
        total = sum(g.n for g in gaps)
        lines.append(f"Дыры: {total}.")
        for gap in gaps:
            lines.append(f"- {gap.symbol} {gap.stream}: {gap.n}")
    else:
        lines.append("Дыр в файле нет (это не сутки VPS).")
    if ping_ms is None:
        lines.append("Пинг: нет замера.")
    else:
        lines.append(f"Пинг: {ping_ms:.1f} мс.")
    text = "\n".join(lines) + "\n"
    if _ADVICE.search(text):
        raise ValueError("daily report must not advise")
    return text
