"""Load-bearing claim not VERIFIED → no pass. Pending unit fixture is not a market."""

from __future__ import annotations

from datetime import UTC, datetime

from capitalizator.card.draft import CardDraft, load_bearing_ok


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


def test_verified_load_bearing_is_ok() -> None:
    assert load_bearing_ok(_card(verdict="VERIFIED")) is True


def test_no_load_bearing_is_not_ok() -> None:
    assert load_bearing_ok(_card(verdict="VERIFIED", bearing=False)) is False
