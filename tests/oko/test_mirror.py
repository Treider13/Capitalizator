"""Mirror: injected spoof / layering / cascade are caught; the report is reproducible."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from tests.oko.conftest import T0, make_book, make_window, mature_passport, quiet_prints

from capitalizator.oko.mirror import (
    MIN_WINDOWS,
    MirrorReport,
    inject_cascade,
    inject_layering,
    inject_spoof,
    run,
)
from capitalizator.oko.passport import Passport
from capitalizator.oko.retina import frame
from capitalizator.oko.shadow import report


def _shadow(raw, passport=None):
    passport = passport or Passport("BTCUSDT")
    return report(raw, frame(raw, passport))


def test_spoof_injection_on_zone_side_is_named(clean_window) -> None:
    assert _shadow(clean_window).label == "CLEAN"
    hit = inject_spoof(clean_window, side="zone", at_s=1, pull_s=3)
    sh = _shadow(hit)
    assert sh.label == "SPOOF"
    assert sh.spoof_side == "zone"
    assert sh.book_trust == 0.0
    # Original window untouched (frozen dataclass; new path objects).
    assert clean_window.adds == ()
    assert len(hit.adds) == 1 and hit.adds[0].qty == Decimal("40")
    kinds = [e.kind for e in hit.wall_events]
    assert kinds == ["appeared", "pulled"]


def test_spoof_injection_on_opposite_side(clean_window) -> None:
    sh = _shadow(inject_spoof(clean_window, side="opp", at_s=2, pull_s=6))
    assert sh.label == "SPOOF"
    assert sh.spoof_side == "opp"


def test_layering_injection_is_named(clean_window) -> None:
    sh = _shadow(inject_layering(clean_window, side="zone", at_s=1, pull_s=4))
    assert sh.label == "LAYERING"
    assert sh.layered_levels == 4


def test_injection_into_a_window_with_a_real_path(clean_window) -> None:
    pre = make_book()
    path = tuple(
        (T0 + timedelta(seconds=s), make_book(seq=s + 1)) for s in (1, 2, 3, 4, 5, 6, 7, 8)
    )
    raw = make_window(book_pre=pre, path=path, trades=quiet_prints())
    assert _shadow(raw).label == "CLEAN"
    hit = inject_spoof(raw, side="zone", at_s=2, pull_s=5)
    assert len(hit.book_path) == len(path)  # existing stamps reused, none duplicated
    standing = [
        b.level("bid", "100.4")
        for ts, b in hit.book_path
        if T0 + timedelta(seconds=2) <= ts < T0 + timedelta(seconds=5)
    ]
    assert standing == [Decimal("50"), Decimal("50"), Decimal("50")]
    assert _shadow(hit).label == "SPOOF"


def test_cascade_injection_needs_mature_passport(clean_window) -> None:
    with pytest.raises(ValueError, match="mature"):
        inject_cascade(clean_window, Passport("BTCUSDT"))
    passport = mature_passport()
    hit = inject_cascade(clean_window, passport)
    sh = _shadow(hit, passport)
    assert sh.label == "CASCADE"
    assert len(hit.trades) > 30


def test_run_is_deterministic_and_passes_on_clean_windows() -> None:
    windows = [make_window(trades=quiet_prints()) for _ in range(MIN_WINDOWS)]
    passport = mature_passport()
    a = run(windows, lambda _s: passport, seed=7, now=T0)
    b = run(windows, lambda _s: passport, seed=7, now=T0)
    assert a == b
    assert a.n_windows == MIN_WINDOWS
    assert a.rate("spoof") == 1.0
    assert a.rate("layering") == 1.0
    assert a.cascade_n == MIN_WINDOWS and a.rate("cascade") == 1.0
    assert a.clean_alarms == 0
    assert a.passed is True
    other = run(windows, lambda _s: passport, seed=8, now=T0)
    assert other.passed is True


def test_run_without_mature_passport_skips_cascade_but_can_pass() -> None:
    windows = [make_window(trades=quiet_prints()) for _ in range(MIN_WINDOWS)]
    rep = run(windows, lambda s: Passport(s), seed=1, now=T0)
    assert rep.cascade_n == 0
    assert rep.rate("cascade") is None
    assert rep.passed is True


def test_too_few_windows_do_not_pass() -> None:
    windows = [make_window(trades=quiet_prints()) for _ in range(MIN_WINDOWS - 1)]
    rep = run(windows, lambda s: Passport(s), seed=1, now=T0)
    assert rep.passed is False


def test_report_roundtrip_and_rates() -> None:
    rep = MirrorReport(
        n_windows=10,
        spoof_hits=9,
        layering_hits=7,
        cascade_n=4,
        cascade_hits=4,
        clean_alarms=2,
        seed=3,
        ran_at=T0.isoformat(),
    )
    assert rep.rate("spoof") == 0.9
    assert rep.passed is False  # layering 0.7 < 0.8
    back = MirrorReport.from_dict(rep.to_dict())
    assert back == rep
    assert rep.to_dict()["passed"] is False
    with pytest.raises(ValueError):
        rep.rate("wash")


def test_bad_offsets_rejected(clean_window) -> None:
    with pytest.raises(ValueError):
        inject_spoof(clean_window, side="zone", at_s=3, pull_s=3)
    with pytest.raises(ValueError):
        inject_spoof(clean_window, side="left", at_s=1, pull_s=3)
