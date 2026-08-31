"""3.15.1 — missing file is empty. Sighting never accepts. No HL ingest."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.whales.pit import WhalePit, WhalePitError

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator"


def test_missing_file_is_empty(tmp_path: Path) -> None:
    got = WhalePit.load(tmp_path / "nope.jsonl")
    assert got.rows == []
    assert WhalePit.load(None).rows == []


def test_slice_before_known_at_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "w.jsonl"
    path.write_text(
        '{"address":"0xabc","known_at":"2026-09-01T12:00:00Z","source":"manual"}\n',
        encoding="utf-8",
    )
    pit = WhalePit.load(path)
    before = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    assert pit.visible(before) == []
    seen = pit.visible(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    assert len(seen) == 1
    assert seen[0].address == "0xabc"


def test_signal_weight_side_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        '{"address":"0xabc","known_at":"2026-09-01T12:00:00Z","source":"manual","signal":"long"}\n',
        encoding="utf-8",
    )
    with pytest.raises(WhalePitError, match="signal"):
        WhalePit.load(path)


def test_missing_known_at_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nok.jsonl"
    path.write_text(
        '{"address":"0xabc","source":"manual"}\n',
        encoding="utf-8",
    )
    with pytest.raises(WhalePitError, match="known_at"):
        WhalePit.load(path)


def test_accept_is_always_false() -> None:
    assert WhalePit().accept() is False


def test_no_hl_ingest_module() -> None:
    assert not (SRC / "whales" / "hl_ingest.py").is_file()
    text = (SRC / "exec" / "strategy_bounce.py").read_text(encoding="utf-8")
    assert "WhalePit" not in text
    assert "hl_ingest" not in text
