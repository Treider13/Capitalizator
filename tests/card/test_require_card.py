"""No card file + require_card → reject. Fixture is a schema dummy, not a live call."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.card.draft import CardDraft, require_card


def _payload() -> dict[str, object]:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC).isoformat()
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
    return {"thesis": "unit fixture, not a market call", "claims": claims}


def test_missing_file_is_rejected() -> None:
    with pytest.raises(ValueError, match="card required"):
        require_card(None, required=True)
    with pytest.raises(ValueError, match="card required"):
        require_card(Path("/no/such/card.json"), required=True)


def test_valid_file_parses(tmp_path: Path) -> None:
    path = tmp_path / "card.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    card = require_card(path, required=True)
    assert isinstance(card, CardDraft)
    assert len(card.claims) == 5
    assert card.claims[0].verdict == "pending"


def test_four_claims_rejected() -> None:
    raw = _payload()
    raw["claims"] = raw["claims"][:4]  # type: ignore[index]
    with pytest.raises(Exception):
        CardDraft.model_validate(raw)


def test_not_required_is_none() -> None:
    assert require_card(None, required=False) is None


def test_verified_in_file_is_rejected(tmp_path: Path) -> None:
    raw = _payload()
    raw["claims"][0]["verdict"] = "VERIFIED"  # type: ignore[index]
    path = tmp_path / "card.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="ManualVerifier"):
        require_card(path, required=True)
