"""0.2.3 — two replays of the same file, same fingerprint after every event."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.book.reconstruct import Book, BookDirty
from capitalizator.recorder.book_diff import BookDiffNormalizer
from capitalizator.recorder.rest_snapshot import BookSnapshot

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ws" / "btc_book_snapshot_20_diffs.jsonl"


def _naive_apply(snap: BookSnapshot, diffs: list[BookSnapshot]) -> tuple[dict, dict, int]:
    bids = {Decimal(p): Decimal(s) for p, s in snap.bids}
    asks = {Decimal(p): Decimal(s) for p, s in snap.asks}
    seq = snap.seq
    for d in diffs:
        for p, s in d.bids:
            px, sz = Decimal(p), Decimal(s)
            if sz == 0:
                bids.pop(px, None)
            else:
                bids[px] = sz
        for p, s in d.asks:
            px, sz = Decimal(p), Decimal(s)
            if sz == 0:
                asks.pop(px, None)
            else:
                asks[px] = sz
        seq = d.seq
    return bids, asks, seq


def _replay(frames: list[dict]) -> tuple[Book, list[bytes]]:
    n = BookDiffNormalizer()
    book = Book()
    fps: list[bytes] = []
    for frame in frames:
        kind, snap = n.parse_frame(frame)
        if kind == "snapshot":
            book.apply_snapshot(snap)
        else:
            book.apply_diff(snap.bids, snap.asks, seq=snap.seq)
        fps.append(book.fingerprint())
    return book, fps


def test_two_replays_match_after_each_event() -> None:
    frames = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]
    _, fps_a = _replay(frames)
    _, fps_b = _replay(frames)
    assert len(fps_a) == 21
    assert fps_a == fps_b
    assert len(set(fps_a)) > 1


def test_replay_matches_independent_dict_book() -> None:
    frames = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]
    n = BookDiffNormalizer()
    parsed = [n.parse_frame(f) for f in frames]
    snap = parsed[0][1]
    diffs = [p[1] for p in parsed[1:]]
    book, _ = _replay(frames)
    naive_b, naive_a, seq = _naive_apply(snap, diffs)
    assert book.seq == seq == 120
    assert book.levels("bid") == naive_b
    assert book.levels("ask") == naive_a


def test_fingerprint_stable_across_price_aliases() -> None:
    a = Book()
    b = Book()
    ts = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)
    a.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=ts,
            seq=1,
            bids=(("60000.0", "5.0"),),
            asks=(("60001.00", "1"),),
        )
    )
    b.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=ts,
            seq=1,
            bids=(("60000", "5"),),
            asks=(("60001", "1"),),
        )
    )
    assert a.fingerprint() == b.fingerprint()


def test_price_alias_does_not_leave_ghost() -> None:
    """Bybit may send 60000.0 then 60000. Those are one price."""
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=1,
            bids=(("60000.0", "5"),),
            asks=(("60000.1", "1"),),
        )
    )
    book.apply_diff((("60000", "0"),), (), seq=2)
    assert book.levels("bid") == {}
    assert book.level("bid", "60000.0") == Decimal("0")
    assert book.level("bid", "60000") == Decimal("0")


def test_zero_size_deletes_level() -> None:
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=1,
            bids=(("60000.0", "5"),),
            asks=(("60000.1", "1"),),
        )
    )
    book.apply_diff((("60000.0", "0"),), (), seq=2)
    assert Decimal("60000.0") not in book.levels("bid")
    assert book.level("bid", "60000.0") == Decimal("0")


def test_imbalance_zero_is_rejected() -> None:
    """`list[-0:]` in Python is the whole list — n=0 must not silently mean 'all'."""
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=1,
            bids=(("100", "1"),),
            asks=(("101", "1"),),
        )
    )
    with pytest.raises(ValueError, match="imbalance n"):
        book.imbalance(0)


def test_negative_size_rejected() -> None:
    book = Book()
    with pytest.raises(ValueError, match="size"):
        book.apply_snapshot(
            BookSnapshot(
                symbol="BTCUSDT",
                exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
                seq=1,
                bids=(("100", "-1"),),
                asks=(("101", "1"),),
            )
        )


def test_best_spread_depth_imbalance() -> None:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=1,
            bids=(("100.0", "2"), ("99.9", "3"), ("99.8", "1")),
            asks=(("100.1", "4"), ("100.2", "5")),
        )
    )
    assert book.best() == (Decimal("100.0"), Decimal("100.1"))
    assert book.spread() == Decimal("0.1")
    assert book.depth_near("bid", "100.0", 1) == Decimal("5")  # 100.0 + 99.9
    imb = book.imbalance(1)
    assert imb == (Decimal("2") - Decimal("4")) / Decimal("6")


def test_diff_before_snapshot_is_dirty() -> None:
    with pytest.raises(BookDirty, match="before snapshot"):
        Book().apply_diff((), (), seq=5)


def test_u_gap_is_applied_like_ccxt() -> None:
    """orderbook.200: a skipped u is still a delta, not a reason to empty the book."""
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=10,
            bids=(("1", "1"),),
            asks=(("2", "1"),),
        )
    )
    book.apply_diff((("3", "4"),), (), seq=12)
    assert book.ready and book.seq == 12
    assert book.level("bid", "3") == Decimal("4")
    assert book.best() == (Decimal("3"), Decimal("2"))


def test_stale_u_is_ignored() -> None:
    """Bybit: same or older `u` is already in the book. Do not reset-local."""
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=10,
            bids=(("1", "1"),),
            asks=(("2", "1"),),
        )
    )
    book.apply_diff((("3", "9"),), (), seq=10)
    book.apply_diff((("4", "8"),), (), seq=9)
    assert book.ready and book.seq == 10
    assert book.best() == (Decimal("1"), Decimal("2"))


def test_u_equals_one_overwrites_like_official_snapshot() -> None:
    book = Book()
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
            seq=50,
            bids=(("1", "1"),),
            asks=(("2", "1"),),
        )
    )
    book.apply_diff((("9", "3"),), (("10", "4"),), seq=1)
    assert book.ready and book.seq == 1
    assert book.best() == (Decimal("9"), Decimal("10"))
    assert book.level("bid", "1") == 0
