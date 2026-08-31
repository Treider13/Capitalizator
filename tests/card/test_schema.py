"""2.11.1 — JSON not on the schema is not a card. No free-text thesis object."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.card.draft import CardDraft, require_card


def _payload() -> dict[str, object]:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC).isoformat()
    return {
        "thesis": "unit fixture",
        "claims": [
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
        ],
    }


def test_invalid_json_is_not_a_card(tmp_path: Path) -> None:
    path = tmp_path / "card.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception):
        require_card(path, required=True)


def test_missing_known_at_is_rejected() -> None:
    raw = _payload()
    del raw["claims"][0]["known_at"]  # type: ignore[index]
    with pytest.raises(Exception):
        CardDraft.model_validate(raw)


def test_free_text_instead_of_object_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "card.json"
    path.write_text(json.dumps("просто текст"), encoding="utf-8")
    with pytest.raises(Exception):
        require_card(path, required=True)
