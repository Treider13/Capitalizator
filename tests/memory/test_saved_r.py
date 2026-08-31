"""Saved-R is shadow, not PnL. Empty total is None. Unknown reason dies."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.memory.saved import SavedLedger


def test_empty_total_is_none() -> None:
    book = SavedLedger()
    assert book.total_saved() is None
    assert book.total_missed() is None


def test_bounce_skip_then_break_is_saved() -> None:
    book = SavedLedger()
    book.record(zone_id="z1", reason="SPLIT")
    done = book.resolve(zone_id="z1", outcome="break")
    assert done.saved_r == Decimal("1")
    assert done.missed_r == Decimal("0")
    assert book.total_saved() == Decimal("1")
    assert book.total_missed() == Decimal("0")


def test_bounce_skip_then_bounce_is_missed_not_profit() -> None:
    book = SavedLedger()
    book.record(zone_id="z1", reason="SILENCE")
    done = book.resolve(zone_id="z1", outcome="bounce")
    assert done.saved_r == Decimal("0")
    assert done.missed_r == Decimal("1")
    assert book.total_saved() == Decimal("0")
    assert book.total_missed() == Decimal("1")


def test_die_is_zero() -> None:
    book = SavedLedger()
    book.record(zone_id="z1", reason="CPI")
    done = book.resolve(zone_id="z1", outcome="die")
    assert done.saved_r == Decimal("0")
    assert done.missed_r == Decimal("0")


def test_pending_is_not_counted() -> None:
    book = SavedLedger()
    book.record(zone_id="z1", reason="no_verified")
    assert book.rows[0].saved_r is None
    assert book.total_saved() is None


def test_unknown_reason_raises() -> None:
    with pytest.raises(ValueError, match="unknown skip reason"):
        SavedLedger().record(zone_id="z1", reason="looked_good")


def test_two_runs_same() -> None:
    def run() -> tuple[Decimal | None, Decimal | None]:
        book = SavedLedger()
        book.record(zone_id="z1", reason="VETO")
        book.resolve(zone_id="z1", outcome="break")
        return book.total_saved(), book.total_missed()

    assert run() == run() == (Decimal("1"), Decimal("0"))
