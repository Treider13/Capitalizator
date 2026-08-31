"""2.12.2 — resolve after horizon. Cannot rewrite the rule after a hit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.authors.ingest import AuthorCall
from capitalizator.authors.resolve import AuthorsResolve, ResolveRule

TS = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _call() -> AuthorCall:
    return AuthorCall(
        author_id="a1",
        ts=TS,
        source="rss",
        text="unit fixture",
        known_at=TS,
        horizon="1h",
    )


def test_up_rule_hits_after_horizon() -> None:
    later = TS + timedelta(hours=1, seconds=1)
    got = AuthorsResolve().close(
        _call(),
        now=later,
        ref_px=Decimal("100"),
        close_px=Decimal("102"),
        rule=ResolveRule(direction="up", threshold_pct=Decimal("0.01")),
    )
    assert got.hit is True
    assert got.resolved_ts == later


def test_before_horizon_stays_open() -> None:
    got = AuthorsResolve().close(
        _call(),
        now=TS + timedelta(minutes=30),
        ref_px=Decimal("100"),
        close_px=Decimal("110"),
        rule=ResolveRule(direction="up", threshold_pct=Decimal("0.01")),
    )
    assert got.hit is None
    assert got.resolved_ts is None


def test_cannot_resolve_twice() -> None:
    later = TS + timedelta(hours=2)
    book = AuthorsResolve()
    first = book.close(
        _call(),
        now=later,
        ref_px=Decimal("100"),
        close_px=Decimal("90"),
        rule=ResolveRule(direction="up", threshold_pct=Decimal("0.01")),
    )
    assert first.hit is False
    with pytest.raises(ValueError, match="after the fact"):
        book.close(
            first,
            now=later,
            ref_px=Decimal("100"),
            close_px=Decimal("120"),
            rule=ResolveRule(direction="up", threshold_pct=Decimal("0.01")),
        )
