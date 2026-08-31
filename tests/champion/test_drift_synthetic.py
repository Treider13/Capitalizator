"""Page-Hinkley: 0.3 → 0.7 errors fires. Flat 0.3 does not. Not live money."""

from __future__ import annotations

from capitalizator.champion.drift import PageHinkley


def _freq(p_ones: int, n_blocks: int) -> list[int]:
    """Deterministic 10-bit block with p_ones ones. No RNG."""
    block = [1] * p_ones + [0] * (10 - p_ones)
    return block * n_blocks


def test_shift_03_to_07_is_drift() -> None:
    series = _freq(3, 40) + _freq(7, 40)
    got = PageHinkley().run(series)
    assert got.drift is True
    assert got.t is not None
    assert got.t > 400


def test_flat_03_is_not_drift() -> None:
    got = PageHinkley().run(_freq(3, 80))
    assert got.drift is False
    assert got.t is None
