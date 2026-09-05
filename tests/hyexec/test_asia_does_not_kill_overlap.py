"""Asia scratches do not close the overlap window. A day −3% still does."""

from __future__ import annotations

from decimal import Decimal

from capitalizator.hyexec.window_halt import WindowHalt


def test_asia_loss_leaves_overlap_open() -> None:
    halt = WindowHalt(start_equity=Decimal("100000"))
    halt.note_window("asia", Decimal("98000"))  # −2%
    assert halt.allow_entry("overlap") is True
    assert halt.allow_entry("asia") is True
    assert halt.allow_aplus("overlap") is False


def test_day_minus_three_closes_every_window() -> None:
    halt = WindowHalt(start_equity=Decimal("100000"))
    halt.note_window("asia", Decimal("97000"))  # −3%
    assert halt.allow_entry("overlap") is False
    assert halt.allow_entry("asia") is False
    assert halt.reason == "day"


def test_week_and_peak_still_global() -> None:
    halt = WindowHalt(start_equity=Decimal("100000"))
    halt.note_window("overlap", Decimal("150000"))  # new peak; day still green
    halt.note_window("overlap", Decimal("112000"))  # −25.3% from peak, day +12%
    assert halt.allow_entry("us") is False
    assert halt.reason == "peak"


def test_fresh_day_allows_aplus_in_overlap_only() -> None:
    halt = WindowHalt(start_equity=Decimal("100000"))
    assert halt.allow_aplus("overlap") is True
    assert halt.allow_aplus("asia") is False
    assert halt.allow_aplus("europe") is False
