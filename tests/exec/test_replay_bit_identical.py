"""0.2.7 — two runs of the small hour, same best() at every checkpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.book.reconstruct import BookDirty
from capitalizator.exec.replay import ReplayEngine
from capitalizator.recorder.gap import SeqFault

TAPE_RECV = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "day_btc_small"
WS_BOOK = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_book_snapshot_20_diffs.jsonl"


def test_small_hour_is_the_same_bytes_as_ws_book_fixture() -> None:
    """day_btc_small is the recorded-hour stand-in, not a second invented tape."""
    assert (FIXTURE / "book.jsonl").read_bytes() == WS_BOOK.read_bytes()


def test_two_runs_same_best() -> None:
    engine = ReplayEngine()
    a = engine.run(FIXTURE)
    b = engine.run(FIXTURE)
    assert len(a) == 21
    assert a == b
    assert [c.best() for c in a] == [c.best() for c in b]
    # Book actually moves: first delta deletes 60000.0 bid.
    assert a[0].best() != a[1].best()
    assert a[0].seq == 100
    assert a[-1].seq == 120


def test_gap_does_not_invent_snapshot(tmp_path: Path) -> None:
    src = (FIXTURE / "book.jsonl").read_text(encoding="utf-8").splitlines()
    frames = [json.loads(line) for line in src if line]
    frames[4]["data"]["u"] = 200  # was 104; hole after 103
    broken = tmp_path / "broken.jsonl"
    broken.write_text("\n".join(json.dumps(f) for f in frames) + "\n", encoding="utf-8")
    with pytest.raises((BookDirty, SeqFault)):
        ReplayEngine().run(broken)


def test_empty_file_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "book.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no book frames"):
        ReplayEngine().run(tmp_path)


def test_run_accepts_jsonl_file_directly() -> None:
    points = ReplayEngine().run(FIXTURE / "book.jsonl")
    assert len(points) == 21
    assert points[0].best_bid is not None
    assert points[0].best_ask is not None


def test_tape_two_runs_identical() -> None:
    engine = ReplayEngine()
    a = engine.tape(FIXTURE, recv_ts=TAPE_RECV)
    b = engine.tape(FIXTURE, recv_ts=TAPE_RECV)
    assert len(a) == 5
    assert a == b
    assert all(e.stream == "trades" for e in a)
    assert all(e.symbol == "BTCUSDT" for e in a)


def test_tape_does_not_change_book_checkpoints() -> None:
    engine = ReplayEngine()
    before = engine.run(FIXTURE)
    assert engine.tape(FIXTURE, recv_ts=TAPE_RECV)
    after = engine.run(FIXTURE)
    assert before == after


def test_missing_trades_is_empty_not_invented(tmp_path: Path) -> None:
    (tmp_path / "book.jsonl").write_text(
        (FIXTURE / "book.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert ReplayEngine().tape(tmp_path, recv_ts=TAPE_RECV) == []


def test_tape_naive_recv_rejected() -> None:
    with pytest.raises(TypeError, match="naive"):
        ReplayEngine().tape(FIXTURE, recv_ts=datetime(2026, 8, 30, 13, 30))
