"""Load-bearing claim not VERIFIED → no pass. Pending unit fixture is not a market."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from capitalizator.card.draft import CardDraft, apply_bind, load_bearing_ok
from capitalizator.verifier.manual import BindReceipt, ManualVerifier


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


def _stamp(card: CardDraft, tmp_path: Path) -> CardDraft:
    q = tmp_path / "q.txt"
    q.write_text(card.claims[0].value + "\n", encoding="utf-8")
    receipt = ManualVerifier().bind(card.claims[0].value, q, card.claims[0].value)
    return apply_bind(card, 0, receipt)


def test_pending_load_bearing_is_not_ok() -> None:
    assert load_bearing_ok(_card(verdict="pending")) is False


def test_verified_load_bearing_is_ok(tmp_path: Path) -> None:
    stamped = _stamp(_card(verdict="pending"), tmp_path)
    assert load_bearing_ok(stamped) is True


def test_no_load_bearing_is_not_ok(tmp_path: Path) -> None:
    stamped = _stamp(_card(verdict="pending", bearing=False), tmp_path)
    assert load_bearing_ok(stamped) is False


def test_raw_verified_string_is_not_enough() -> None:
    with pytest.raises(AttributeError):
        apply_bind(_card(verdict="pending"), 0, "VERIFIED")  # type: ignore[arg-type]


def test_receipt_for_other_claim_is_rejected(tmp_path: Path) -> None:
    card = _card(verdict="pending")
    q = tmp_path / "q.txt"
    q.write_text("other\n", encoding="utf-8")
    other = BindReceipt(claim="other", verdict="VERIFIED", sql_path=str(q))
    with pytest.raises(ValueError, match="receipt does not match"):
        apply_bind(card, 0, other)


def test_verified_without_query_file_is_rejected() -> None:
    card = _card(verdict="pending")
    forged = BindReceipt(claim=card.claims[0].value, verdict="VERIFIED", sql_path=None)
    with pytest.raises(ValueError, match="query file"):
        apply_bind(card, 0, forged)


def test_forged_path_without_file_is_rejected() -> None:
    card = _card(verdict="pending")
    forged = BindReceipt(claim=card.claims[0].value, verdict="VERIFIED", sql_path="missing.sql")
    with pytest.raises(ValueError, match="query file"):
        apply_bind(card, 0, forged)


def test_tampered_query_file_cannot_stamp(tmp_path: Path) -> None:
    card = _card(verdict="pending")
    q = tmp_path / "q.txt"
    q.write_text(card.claims[0].value + "\n", encoding="utf-8")
    receipt = ManualVerifier().bind(card.claims[0].value, q, card.claims[0].value)
    q.write_text("подмена\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches"):
        apply_bind(card, 0, receipt)


def test_human_first_fact_field_is_rejected() -> None:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    claims = [
        {
            "type": "unit",
            "subject": "BTCUSDT",
            "value": f"fixture-{i}",
            "as_of": stamp,
            "known_at": stamp,
            "horizon": "1h",
            "load_bearing": i == 0,
        }
        for i in range(5)
    ]
    with pytest.raises(ValidationError):
        CardDraft.model_validate(
            {"thesis": "unit fixture", "claims": claims, "first_fact": "DEFEND"}
        )
