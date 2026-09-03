"""Sessions release: k_atr is an input, liquidation clusters are magnets, and a stop
farther than max_stop_atr from the entry refuses the setup instead of fitting it."""

from __future__ import annotations

from decimal import Decimal

import pytest

from capitalizator.exec.smart_stop import initial_stop

TICK = Decimal("0.1")


def test_k_atr_is_applied_and_recorded() -> None:
    narrow = initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                          spread=None, k_atr=Decimal("0.5"))
    wide = initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                        spread=None, k_atr=Decimal("0.8"))
    assert narrow.buffer == Decimal("50") and wide.buffer == Decimal("80")
    assert narrow.components["k_atr"] == "0.5" and wide.components["k_atr"] == "0.8"
    assert wide.stop < narrow.stop  # long: a wider buffer sits lower
    with pytest.raises(ValueError):
        initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=None, spread=None,
                     k_atr=Decimal("0"))


def test_liquidation_cluster_pushes_the_stop_past_it() -> None:
    # buffered stop lands at 98950; a liquidation cluster sits 2 ticks below it
    base = initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                        spread=None, k_atr=Decimal("0.5"))
    assert base.stop == Decimal("98950.0") and not base.moved_for_cluster
    pushed = initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                          spread=None, k_atr=Decimal("0.5"), liq_levels=(Decimal("98949.8"),))
    assert pushed.moved_for_cluster and pushed.stop <= Decimal("98949.8") - TICK * 5
    assert pushed.components["liq_levels_near"] == "1"
    # a cluster far from the stop is not a magnet
    far = initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                       spread=None, k_atr=Decimal("0.5"), liq_levels=(Decimal("98000"),))
    assert far.stop == base.stop and "liq_levels_near" not in far.components


def test_max_stop_atr_refuses_a_setup_whose_invalidation_is_too_far() -> None:
    ok = initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                      spread=None, entry=Decimal("99200"), max_stop_atr=Decimal("2.5"))
    assert ok.components["stop_atr"] == "2.5" and ok.components["max_stop_atr"] == "2.5"
    with pytest.raises(ValueError, match="stop_too_wide"):
        initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=Decimal("100"),
                     spread=None, entry=Decimal("99300"), max_stop_atr=Decimal("2.5"))
    # no ATR → the ceiling cannot be measured and is not applied (never a guess)
    initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=None, spread=None,
                 entry=Decimal("120000"), max_stop_atr=Decimal("2.5"))
    with pytest.raises(ValueError):
        initial_stop(side="buy", structural=Decimal("99000"), tick=TICK, atr=None, spread=None,
                     max_stop_atr=Decimal("0"))
