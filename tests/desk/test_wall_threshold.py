"""A wall is loud relative to *this* symbol's book, not a coin count or a fixed notional.

Before: `WallWatch(symbol, min_size=50)` for every symbol (every DOGE level a wall, no SOL
level ever one), then `$3M / px` (no alt level ever a wall). Now the threshold is the
symbol's own zone-side depth norm from the ОКО Passport (median over ≥ mature_n touch
windows); before the Passport matures the notional floor applies; without a price there
is no wall watch at all — never a guessed `50`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.book.wall_watch import WallWatch
from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot

TS = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "v")), user_mode="off")


def _mature(desk: DeskLoop, symbol: str, depth: str, n: int | None = None) -> None:
    passport = desk.oko.passport_for(symbol)
    for _ in range(n or desk.config.mature_n):
        passport.depth.add(Decimal(depth))
    assert passport.depth.mature


def test_no_price_and_no_norm_means_no_wall_watch(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    watch = desk._wall_for("DOGEUSDT")
    assert watch.min_size is None
    book = Book()
    book.apply_snapshot(
        BookSnapshot(symbol="DOGEUSDT", exchange_ts=TS, seq=1,
                     bids=(("0.1", "1000000"),), asks=(("0.1001", "1"),))
    )
    # A million DOGE on the bid is not called a wall by a desk that has no norm yet.
    assert watch.on_book_and_trade(book, ts=TS) == []


def test_immature_passport_uses_notional_floor_per_price(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.last_price["BTCUSDT"] = Decimal("60000")
    desk.last_price["DOGEUSDT"] = Decimal("0.1")
    floor = desk.config.wall_min_notional
    assert desk._wall_for("BTCUSDT").min_size == floor / Decimal("60000")
    assert desk._wall_for("DOGEUSDT").min_size == floor / Decimal("0.1")


def test_mature_passport_sets_threshold_from_own_depth_norm(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.last_price["SUIUSDT"] = Decimal("2")
    _mature(desk, "SUIUSDT", "40000")  # typical zone-side depth: 40k SUI
    watch = desk._wall_for("SUIUSDT")
    assert watch.min_size == Decimal("40000") * desk.config.wall_depth_mult
    # $3M / 2 = 1.5M SUI would never trigger; 40k × mult does.
    assert watch.min_size < desk.config.wall_min_notional / Decimal("2")


def test_threshold_follows_the_norm_as_it_changes(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.last_price["SOLUSDT"] = Decimal("150")
    _mature(desk, "SOLUSDT", "1000")
    first = desk._wall_for("SOLUSDT").min_size
    passport = desk.oko.passport_for("SOLUSDT")
    for _ in range(200):
        passport.depth.add(Decimal("5000"))
    second = desk._wall_for("SOLUSDT").min_size
    assert first is not None and second is not None and second > first


def test_raising_threshold_does_not_fake_a_pull() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = Book()
    book.apply_snapshot(
        BookSnapshot(symbol="BTCUSDT", exchange_ts=TS, seq=1,
                     bids=(("60000", "60"),), asks=(("60001", "1"),))
    )
    assert [e.kind for e in watch.on_book_and_trade(book, ts=TS)] == ["appeared"]
    watch.set_min_size(Decimal("100"))
    # The 60 BTC level is still there; it simply is no longer a wall. No "pulled".
    assert watch.on_book_and_trade(book, ts=TS) == []
    assert watch.tracked_count() == 0


def test_disabling_threshold_drops_tracked_walls_silently() -> None:
    watch = WallWatch("BTCUSDT", min_size=Decimal("50"))
    book = Book()
    book.apply_snapshot(
        BookSnapshot(symbol="BTCUSDT", exchange_ts=TS, seq=1,
                     bids=(("60000", "60"),), asks=(("60001", "1"),))
    )
    watch.on_book_and_trade(book, ts=TS)
    watch.set_min_size(None)
    assert watch.on_book_and_trade(book, ts=TS) == []
    assert watch.tracked_count() == 0
