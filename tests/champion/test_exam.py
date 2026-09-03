"""Contour C exam: champion vs challenger on closed paper results; promotion is a label
flip that only a passing exam plus an operator ack can produce."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from capitalizator.champion.exam import exam
from capitalizator.champion.shadow_width import ShadowWidth
from capitalizator.champion.veto_shadow import VetoShadow

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _rows(source: str, rs: list[str]) -> list[dict]:
    return [
        {"source": source, "entry_px": "100", "r_net": r, "closed_at": (T0 + timedelta(minutes=i)).isoformat()}
        for i, r in enumerate(rs)
    ]


def test_exam_fails_on_too_few_or_no_edge_and_passes_on_a_better_challenger() -> None:
    champ = _rows("shadow", ["1", "-1"] * 20)  # 40 trades, expectancy 0
    weak = _rows("fade", ["0.5", "-1"] * 20)  # worse
    rep = exam(champ + weak, now=T0)
    assert rep.passed is False and "expectancy" in " ".join(rep.reasons)
    few = _rows("fade", ["2"] * 10)
    rep2 = exam(champ + few, now=T0)
    assert rep2.passed is False and any("n=10" in r for r in rep2.reasons)
    strong = _rows("fade", ["1.5", "1.5", "-1"] * 14)  # 42 trades, mean ≈ 0.67, shallow DD
    rep3 = exam(champ + strong, now=T0)
    assert rep3.passed is True and rep3.challenger.lower_r is not None and rep3.challenger.lower_r > 0
    assert rep3.challenger.max_dd_r is not None and rep3.challenger.max_dd_r <= rep3.champion.max_dd_r
    assert rep3.to_payload()["challenger"]["n"] == 42


def test_promote_without_ack_still_refuses_and_with_ack_returns_the_report() -> None:
    for obj in (ShadowWidth(), VetoShadow()):
        with pytest.raises(ValueError, match="no auto promote"):
            obj.promote()
        rep = obj.promote(_rows("shadow", ["1"] * 30) + _rows("fade", ["1"] * 30), now=T0, ack=True)
        assert rep.passed is False  # equal expectancy is not "better"
