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


def _phase_exit(**fields: object) -> dict[str, object]:
    row: dict[str, object] = {
        "had_compress": True,
        "bar_quality": "live",
        "zone_side": "support",
        "htf_h4": "long",
        "htf_d1": "unknown",
        "cav_label": "THROUGH",
        "zlg_label": "RETREAT",
        "tape_eaten": True,
        "shadow_would": False,
    }
    row.update(fields)
    return row


def test_challenger_is_phase_exit_not_champion_filter() -> None:
    first_print = {
        "shadow_would": True,
        "shadow_tag": "bounce",
        "bar_quality": "live",
        "cav_label": "REJECT",
        "zlg_label": "DEFEND",
        "tape_eaten": False,
        "had_compress": False,
        "zone_side": "support",
        "htf_h4": "long",
    }
    assert challenger_on(first_print) is False
    exit_row = _phase_exit()
    assert challenger_on(exit_row) is True
    assert challenger_tag(exit_row) == "phase_exit_breakout"
    assert challenger_on(_phase_exit(had_compress=False)) is False
    assert challenger_on(_phase_exit(cav_label="COMPRESS")) is False
    assert challenger_on(_phase_exit(bar_quality="stagnant")) is False
    assert challenger_on(_phase_exit(htf_h4="unknown", htf_d1="unknown")) is False
    assert challenger_on(_phase_exit(htf_h4="long")) is True


def test_challenger_accepts_eaten_retreat_or_through() -> None:
    through = _phase_exit(zlg_label="DEFEND", tape_eaten=False)
    assert challenger_on(through) is True
    pour = _phase_exit(cav_label="REJECT", zlg_label="RETREAT", tape_eaten=True)
    assert challenger_on(pour) is True
    assert challenger_on(_phase_exit(cav_label="REJECT", zlg_label="DEFEND", tape_eaten=False)) is False
    assert challenger_on(_phase_exit(cav_label="THROUGH", tape_eaten=None, zlg_label="SILENCE")) is True


def test_persist_empty_is_null_not_zero(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    snap = persist_day(knowledge, "2026-08-31")
    assert snap.r_shadow is None
    assert snap.r_challenger is None
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] is None
    assert overlay["r_challenger"] is None


def test_persist_writes_challenger_r_not_champion(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    knowledge.put_journal_touch(
        "c1",
        {
            "touch_ts": "2026-08-31T14:10:00+00:00",
            "shadow_would": False,
            "outcome": "break",
            **_phase_exit(),
        },
    )
    persist_day(knowledge, "2026-08-31")
    overlay = knowledge.get_overlay("2026-08-31:shadow")
    assert overlay is not None
    assert overlay["r_shadow"] is None
    assert overlay["r_challenger"] == "1"


def test_summarize_scores_challenger_as_breakout() -> None:
    snap = summarize(
        [
            {
                "touch_ts": "2026-08-31T14:10:00+00:00",
                "shadow_would": False,
                "outcome": "bounce",
                **_phase_exit(),
            }
        ],
        day="2026-08-31",
    )
    assert snap.n_would == 0
    assert snap.n_challenger == 1
    assert snap.r_shadow is None
    assert snap.r_challenger == Decimal("-1")


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
    assert overlay["r_challenger"] is None
