"""24/7 shadow R. Empty is None. Challenger never opens size."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from capitalizator.champion.shadow_day import (
    challenger_on,
    challenger_tag,
    idea_r,
    persist_day,
    summarize,
)
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


def test_pending_is_unknown() -> None:
    assert idea_r("bounce", None) is None
    assert idea_r("bounce", "pending") is None


def test_bounce_taken_then_holds_is_plus() -> None:
    assert idea_r("bounce", "bounce") == Decimal("1")
    assert idea_r("bounce", "break") == Decimal("-1")
    assert idea_r("bounce", "die") == Decimal("0")


def test_breakout_taken_then_breaks_is_plus() -> None:
    assert idea_r("breakout", "break") == Decimal("1")
    assert idea_r("breakout", "bounce") == Decimal("-1")


def test_empty_day_r_is_none() -> None:
    snap = summarize([], day="2026-08-31")
    assert snap.r_shadow is None
    assert snap.n_would == 0
    assert snap.n_challenger == 0


def test_other_day_is_ignored() -> None:
    snap = summarize(
        [
            {
                "touch_ts": "2026-08-30T16:30:00+00:00",
                "shadow_would": True,
                "shadow_tag": "bounce",
                "outcome": "bounce",
            }
        ],
        day="2026-08-31",
    )
    assert snap.n_would == 0
    assert snap.r_shadow is None


def test_resolved_sum_is_honest() -> None:
    snap = summarize(
        [
            {
                "touch_ts": "2026-08-31T14:10:00+00:00",
                "shadow_would": True,
                "shadow_tag": "bounce",
                "outcome": "bounce",
            },
            {
                "touch_ts": "2026-08-31T15:10:00+00:00",
                "shadow_would": True,
                "shadow_tag": "bounce",
                "outcome": "break",
            },
            {
                "touch_ts": "2026-08-31T16:10:00+00:00",
                "shadow_would": True,
                "shadow_tag": "bounce",
                "outcome": "pending",
            },
        ],
        day="2026-08-31",
    )
    assert snap.n_would == 3
    assert snap.n_resolved == 2
    assert snap.r_shadow == Decimal("0")


def test_challenger_needs_phase_exit() -> None:
    bounce = {
        "shadow_would": True,
        "shadow_tag": "bounce",
        "bar_quality": "live",
        "cav_label": "REJECT",
        "zlg_label": "DEFEND",
        "tape_eaten": False,
    }
    assert challenger_on(bounce) is True
    assert challenger_tag(bounce) == "phase_exit_bounce"
    compress = dict(bounce, cav_label="COMPRESS")
    assert challenger_on(compress) is False
    stagnant = dict(bounce, bar_quality="stagnant")
    assert challenger_on(stagnant) is False
    eaten = dict(bounce, tape_eaten=True)
    assert challenger_on(eaten) is False
    unknown = dict(bounce, tape_eaten=None)
    assert challenger_on(unknown) is False


def test_challenger_breakout_needs_eaten_retreat() -> None:
    row = {
        "shadow_would": True,
        "shadow_tag": "breakout",
        "bar_quality": "live",
        "cav_label": "THROUGH",
        "zlg_label": "RETREAT",
        "tape_eaten": True,
    }
    assert challenger_on(row) is True
    assert challenger_on(dict(row, tape_eaten=False)) is False


def test_persist_empty_is_null_not_zero(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    snap = persist_day(knowledge, "2026-08-31")
    assert snap.r_shadow is None
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] is None


def test_persist_keeps_demo_and_writes_measured_r(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_overlay("2026-08-31:shadow", r_demo="1.5")
    knowledge.put_journal_touch(
        "t1",
        {
            "touch_ts": "2026-08-31T14:10:00+00:00",
            "shadow_would": True,
            "shadow_tag": "bounce",
            "outcome": "bounce",
        },
    )
    persist_day(knowledge, "2026-08-31")
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] == "1"
    assert overlay["r_demo"] == "1.5"
