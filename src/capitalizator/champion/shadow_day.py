"""24/7 champion shadow R from the journal. Empty is None, not a fake zero.

Challenger is a second class on the same touch: HTF with the exit,
had COMPRESS, then THROUGH or eaten+RETREAT. It never opens size.
Does not import signer. Does not promote.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from capitalizator.ops.knowledge import Knowledge

R_UNIT = Decimal("1")
PENDING = frozenset({None, "", "pending"})
_UNSET_HTF = frozenset({None, "", "unknown", "box"})


@dataclass(frozen=True)
class ShadowDay:
    day: str
    n_would: int
    n_resolved: int
    r_shadow: Decimal | None
    n_challenger: int
    r_challenger: Decimal | None


def _truthy(value: object) -> bool:
    return value is True or value == "true" or value == "True" or value == 1


def row_day_utc(row: Mapping[str, Any]) -> str | None:
    raw = str(row.get("touch_ts") or "").strip()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10] if len(raw) >= 10 and raw[4] == "-" else None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(UTC).date().isoformat()


def idea_of(row: Mapping[str, Any]) -> str:
    tag = str(row.get("shadow_tag") or row.get("idea") or "bounce")
    if tag == "failed_break_bounce":
        return "bounce"
    if tag in {"bounce", "breakout"}:
        return tag
    return "bounce"


def idea_r(idea: str, outcome: str | None) -> Decimal | None:
    """Would-have-taken R. Inverse of skip saved-R. Pending is unknown."""
    if outcome in PENDING:
        return None
    if outcome == "die":
        return Decimal("0")
    if idea == "bounce":
        if outcome == "bounce":
            return R_UNIT
        if outcome == "break":
            return -R_UNIT
    if idea == "breakout":
        if outcome == "break":
            return R_UNIT
        if outcome == "bounce":
            return -R_UNIT
    return Decimal("0")


def _effective_htf(row: Mapping[str, Any]) -> str | None:
    d1 = row.get("htf_d1")
    h4 = row.get("htf_h4")
    if d1 not in _UNSET_HTF:
        return str(d1)
    if h4 not in _UNSET_HTF:
        return str(h4)
    return None


def challenger_on(row: Mapping[str, Any]) -> bool:
    """Phase-exit after COMPRESS. Not champion ACCORD. Not first-print bounce.

    HTF is the same clock CAV already used: a known trend (not unknown/box).
    CAV stamps THROUGH/REJECT only when that trend is with the bounce or unset;
    requiring the opposite side here would make the flag dead on every real row.
    """
    if not _truthy(row.get("had_compress")):
        return False
    if row.get("bar_quality") != "live":
        return False
    if _effective_htf(row) is None:
        return False
    cav = row.get("cav_label")
    if cav in {None, "NOISE", "DRIFT", "COMPRESS"}:
        return False
    through = cav == "THROUGH"
    poured = row.get("zlg_label") == "RETREAT" and row.get("tape_eaten") is True
    return through or poured


def challenger_tag(row: Mapping[str, Any]) -> str | None:
    if not challenger_on(row):
        return None
    return "phase_exit_breakout"


def summarize(rows: list[Mapping[str, Any]], *, day: str) -> ShadowDay:
    day_rows = [row for row in rows if row_day_utc(row) == day]
    would = [row for row in day_rows if _truthy(row.get("shadow_would"))]
    scored: list[Decimal] = []
    for row in would:
        got = idea_r(idea_of(row), None if row.get("outcome") is None else str(row.get("outcome")))
        if got is not None:
            scored.append(got)
    chall = [row for row in day_rows if challenger_on(row)]
    chall_scored: list[Decimal] = []
    for row in chall:
        got = idea_r("breakout", None if row.get("outcome") is None else str(row.get("outcome")))
        if got is not None:
            chall_scored.append(got)
    return ShadowDay(
        day=day,
        n_would=len(would),
        n_resolved=len(scored),
        r_shadow=None if not scored else sum(scored, Decimal("0")),
        n_challenger=len(chall),
        r_challenger=None if not chall_scored else sum(chall_scored, Decimal("0")),
    )


def persist_day(knowledge: Knowledge, day: str) -> ShadowDay:
    """Write measured R. Unknown stays NULL. Never invents 0. No orders."""
    snap = summarize(knowledge.journal_rows(), day=day)
    setup = f"{day}:shadow"
    prev = knowledge.get_overlay(setup) or {}
    r_txt = None if snap.r_shadow is None else format(snap.r_shadow, "f")
    chall_txt = None if snap.r_challenger is None else format(snap.r_challenger, "f")
    knowledge.put_overlay(
        setup,
        r_shadow=r_txt,
        r_demo=prev.get("r_demo"),
        r_live=prev.get("r_live"),
        r_challenger=chall_txt,
    )
    return snap
