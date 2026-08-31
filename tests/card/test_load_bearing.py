"""Load-bearing claim not VERIFIED → no pass. Pending unit fixture is not a market."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.card.draft import CardDraft, apply_bind, load_bearing_ok
from capitalizator.verifier.manual import BindReceipt


def _card(*, verdict: str, bearing: bool = True) -> CardDraft:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    claims = [
        {
            "type": "unit",
            "subject": "BTCUSDT",
            "value": f"fixture-{i}",
            "as_of": stamp,
            "known_at": stamp,
            "horizon": "1h",
            "load_bearing": bearing and i == 0,
            "verdict": verdict if i == 0 else "pending",
        }
        for i in range(5)
    ]
    return CardDraft.model_validate({"thesis": "unit fixture", "claims": claims})


def test_pending_load_bearing_is_not_ok() -> None:
    assert load_bearing_ok(_card(verdict="pending")) is False


def _receipt(card: CardDraft, *, verdict: str = "VERIFIED") -> BindReceipt:
    return BindReceipt(claim=card.claims[0].value, verdict=verdict, sql_path="fixture.sql")


def test_verified_load_bearing_is_ok() -> None:
    card = _card(verdict="pending")
    stamped = apply_bind(card, 0, _receipt(card))
    assert load_bearing_ok(stamped) is True


def test_no_load_bearing_is_not_ok() -> None:
    card = _card(verdict="pending", bearing=False)
    stamped = apply_bind(card, 0, _receipt(card))
    assert load_bearing_ok(stamped) is False


def test_raw_verified_string_is_not_enough() -> None:
    with pytest.raises(AttributeError):
        apply_bind(_card(verdict="pending"), 0, "VERIFIED")  # type: ignore[arg-type]


def test_receipt_for_other_claim_is_rejected() -> None:
    card = _card(verdict="pending")
    other = BindReceipt(claim="other", verdict="VERIFIED", sql_path="fixture.sql")
    with pytest.raises(ValueError, match="receipt does not match"):
        apply_bind(card, 0, other)


def test_verified_without_query_file_is_rejected() -> None:
    card = _card(verdict="pending")
    forged = BindReceipt(claim=card.claims[0].value, verdict="VERIFIED", sql_path=None)
    with pytest.raises(ValueError, match="query file"):
        apply_bind(card, 0, forged)
