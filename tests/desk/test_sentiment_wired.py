"""Э5: desk sentiment uses news_macro.sentiment.decide on monthly F&G."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def _fng(kn, n: int, value: str, *, start: datetime) -> None:
    for i in range(n):
        ts = start + timedelta(days=i)
        kn.put_intel_item(
            f"fng-{i}",
            kind="fng",
            source_id="fng:alternative.me",
            known_at=ts.isoformat(),
            payload={"value": value, "classification": "Greed"},
        )


def test_monthly_greed_cuts_via_decide(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    _fng(kn, 20, "90", start=NOW - timedelta(days=20))
    desk = DeskLoop(knowledge=kn, user_mode="off")
    assert desk._sentiment_multiplier(NOW) == Decimal("0.7")
    assert desk._sentiment_reason == "monthly_greed"


def test_sparse_fng_is_not_a_month(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    _fng(kn, 5, "90", start=NOW - timedelta(days=5))
    desk = DeskLoop(knowledge=kn, user_mode="off")
    assert desk._sentiment_multiplier(NOW) == Decimal("1")
    assert desk._sentiment_reason == "sentiment_not_month"
