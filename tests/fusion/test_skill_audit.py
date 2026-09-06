"""Independent faults and unavailable evidence must not become entry permission."""

import time

import pytest
from tests.fusion.test_review import PRICES, make_bars

from capitalizator.fusion.config import Config
from capitalizator.fusion.engine import Shared
from capitalizator.fusion.external import gamma
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.structure import Structure, parse_history


def test_private_recovery_cannot_clear_concurrent_disk_halt(tmp_path):
    runtime = Runtime(tmp_path, Config())
    runtime.shared.halt("private_queue_overflow: reconcile required")
    runtime.private_overflow_at = 10

    class Reconciled:
        @property
        def last_reconcile(self):
            runtime.shared.halt("disk_space_low")
            return 20

    runtime.executor = Reconciled()
    runtime.supervisor.beat = lambda _: runtime.supervisor.stop.set()
    try:
        runtime._maintenance()
        assert runtime.shared.halted
        assert "disk_space_low" in runtime.shared.reason
    finally:
        runtime.store.close()


def test_history_gap_cannot_be_used_as_contiguous_structure():
    structure = Structure()
    for tf, seconds in (("15m", 900), ("1m", 60)):
        bars = make_bars(tf, seconds, PRICES)
        for i, bar in enumerate(bars):
            if i != len(bars) - 3:
                structure.add(bar, 0.01)
    assert not structure.pair(1, 108, 106.5, 109, 20001)["allowed"]


def test_conflicting_history_duplicates_are_rejected():
    raw = [["0", "100", "102", "99", "101", "10"],
           ["0", "100", "103", "99", "102", "10"]]
    with pytest.raises(ValueError, match="conflicting"):
        parse_history("BTCUSDT", "1m", raw, 100)


@pytest.mark.parametrize("field,value", [("gamma", ""), ("markIv", ""), ("gamma", "-0.1")])
def test_missing_or_invalid_option_evidence_is_not_zero(field, value):
    row = {"symbol": "BTC-25DEC26-50000-C", "openInterest": "8", "gamma": ".001",
           "underlyingPrice": "50000", "markIv": ".5"}
    with pytest.raises(ValueError):
        gamma([{**row, field: value}], time.time())


def test_identical_duplicate_history_is_idempotent():
    row = ["0", "100", "102", "99", "101", "10"]
    assert len(parse_history("BTCUSDT", "1m", [row, row], 100)) == 1


def test_history_repair_restores_structure_without_synthetic_bars():
    structure = Structure()
    complete = make_bars("15m", 900, PRICES) + make_bars("1m", 60, PRICES)
    missing = complete[-3]
    structure.seed([b for b in complete if b != missing], 0.01)
    assert not structure.pair(1, 108, 106.5, 109, 20001)["allowed"]
    structure.seed([missing], 0.01)
    assert structure.pair(1, 108, 106.5, 109, 20001)["allowed"]


def test_missing_candles_cannot_create_a_fair_value_gap():
    structure = Structure()
    bars = make_bars("1m", 60, [100, 101, 102, 110, 111])
    structure.seed([bars[0], bars[1], bars[-1]], 0.01)
    assert structure.cache["1m"]["zones"] == []


def test_recovery_cannot_clear_new_incident_of_same_kind():
    shared = Shared()
    shared.halt("private_queue_overflow: reconcile required")
    observed = dict(shared.halts)
    shared.halt("private_queue_overflow: reconcile required")
    shared.clear_halts(observed)
    assert shared.halted
    shared.clear_halts(dict(shared.halts))
    assert not shared.halted


def test_feed_recovery_preserves_unrelated_faults():
    shared = Shared()
    shared.halt("disk_space_low")
    shared.halt("recovering_feed")
    shared.halt("worker_stale:broker")
    shared.halt("worker_stale:news")
    shared.clear_halts({"recovering_feed": shared.halts["recovering_feed"]})
    assert shared.halted
    assert set(shared.halts) == {"disk_space_low", "worker_stale:broker", "worker_stale:news"}


def test_zero_open_interest_does_not_require_unused_greeks():
    assert not gamma([{"openInterest": "0"}], time.time())["available"]


def test_old_history_gap_does_not_erase_new_break_direction():
    structure = Structure()
    # Separate old history from a complete, usable current segment.
    older = make_bars("15m", 900, [90], end=1000)
    current = make_bars("15m", 900, PRICES + [130], end=20900)
    structure.seed(older + current, 0.01)
    assert structure.cache["15m"]["bos"] == 1
    before = dict(structure.previous_break)
    structure.add(make_bars("15m", 900, [110], end=21800)[0], 0.01)
    assert structure.cache["15m"]["bos"] == 0
    assert structure.previous_break == before
