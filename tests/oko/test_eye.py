"""OkoEye: observe → passport learns after; mirror after 5 windows; judge; save/load."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from tests.oko.conftest import T0, make_window, quiet_prints
from tests.oko.test_weather import _bars

from capitalizator.oko.eye import MIRROR_EVERY, OkoEye
from capitalizator.oko.forecast import Sample, class_key
from capitalizator.oko.mirror import MIN_WINDOWS
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault


class DictStore:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def meta(self, key: str) -> str | None:
        return self.rows.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self.rows[key] = value

    def meta_prefix(self, prefix: str) -> dict[str, str]:
        return {k: v for k, v in self.rows.items() if k.startswith(prefix)}


def test_observe_window_learns_passport_after_the_frame() -> None:
    eye = OkoEye(working_tf="15m")
    win = eye.observe_window(make_window(trades=quiet_prints()), touch_id="t1", now=T0)
    assert win.frame.passport_mature is False
    assert eye.passport_for("BTCUSDT").depth.n == 1
    assert win.shadow.label == "CLEAN"
    assert win.touch_id == "t1"


def test_mirror_runs_after_five_windows_and_every_five() -> None:
    eye = OkoEye(working_tf="15m")
    assert eye.mirror_ok is False
    for i in range(MIN_WINDOWS - 1):
        eye.observe_window(make_window(trades=quiet_prints()), touch_id=f"t{i}", now=T0)
    assert eye.mirror is None
    eye.observe_window(make_window(trades=quiet_prints()), touch_id="t5", now=T0)
    assert eye.mirror is not None
    assert eye.mirror.n_windows == MIN_WINDOWS
    assert eye.mirror_ok is True
    first = eye.mirror
    for i in range(MIRROR_EVERY - 1):
        eye.observe_window(make_window(trades=quiet_prints()), touch_id=f"u{i}", now=T0)
    assert eye.mirror is first
    eye.observe_window(make_window(trades=quiet_prints()), touch_id="u9", now=T0)
    assert eye.mirror is not first
    assert eye.mirror.n_windows == MIN_WINDOWS * 2


def test_judge_blind_and_with_window() -> None:
    eye = OkoEye(working_tf="15m")
    # A blind touch has no Footprint: its class carries '?', not NONE.
    blind_key = class_key(idea="bounce", cav="REJECT", zlg="DEFEND", regime="UNKNOWN")
    blind_samples = [
        Sample(symbol="BTCUSDT", class_key=blind_key, outcome="bounce") for _ in range(25)
    ]
    blind = eye.judge(
        idea="bounce",
        zone_side="support",
        window=None,
        cav="REJECT",
        zlg="DEFEND",
        samples=blind_samples,
        symbol="BTCUSDT",
    )
    assert blind.voice == 0
    assert blind.label == "UNKNOWN"
    assert blind.footprint == "NONE" and blind.footprint_side is None
    assert blind.pred_set == frozenset({"bounce"})  # forecast written, not voted
    key = class_key(idea="bounce", cav="REJECT", zlg="DEFEND", regime="UNKNOWN", footprint="NONE")
    samples = [Sample(symbol="BTCUSDT", class_key=key, outcome="bounce") for _ in range(25)]
    win = eye.observe_window(make_window(trades=quiet_prints()), touch_id="t", now=T0)
    assert win.footprint.label == "NONE"
    assert len(win.fingerprint) == 13
    seen = eye.judge(
        idea="bounce", zone_side="support", window=win, cav="REJECT", zlg="DEFEND", samples=samples
    )
    # Mirror not run yet (one window) caps +1 to 0; the forecast alone is not enough.
    assert seen.voice == 0
    assert "mirror not passed" in seen.reason
    assert seen.regime == "UNKNOWN"
    with pytest.raises(ValueError):
        eye.judge(idea="bounce", zone_side="support", window=None, cav=None, zlg=None, samples=[])


def test_plus_one_needs_weather_mirror_and_decisive_forecast() -> None:
    eye = OkoEye(working_tf="15m")
    rng = random.Random(9)
    for bar in _bars([rng.gauss(0, 0.002) for _ in range(60)]):
        eye.on_bar_close(bar)
    regime = eye.weather_report("BTCUSDT").regime
    assert regime in {"RANGE", "TREND"}
    key = class_key(idea="bounce", cav="REJECT", zlg="DEFEND", regime=regime, footprint="NONE")
    samples = [Sample(symbol="BTCUSDT", class_key=key, outcome="bounce") for _ in range(25)]
    win = None
    for i in range(MIN_WINDOWS):
        win = eye.observe_window(make_window(trades=quiet_prints()), touch_id=f"t{i}", now=T0)
    assert eye.mirror_ok is True
    assert win is not None
    v = eye.judge(
        idea="bounce", zone_side="support", window=win, cav="REJECT", zlg="DEFEND", samples=samples
    )
    assert v.voice == 1
    assert v.regime == regime


def test_learn_feeds_memory_and_die_is_skipped() -> None:
    eye = OkoEye(working_tf="15m")
    win = eye.observe_window(make_window(trades=quiet_prints()), touch_id="t", now=T0)
    assert eye.learn(
        symbol="BTCUSDT", fingerprint=win.fingerprint, idea="bounce", outcome="break", ts=T0
    )
    assert not eye.learn(
        symbol="BTCUSDT", fingerprint=win.fingerprint, idea="bounce", outcome="die", ts=T0
    )
    assert eye.memory_for("BTCUSDT").n == 1


def test_save_and_load_roundtrip_dict_store() -> None:
    eye = OkoEye(working_tf="15m")
    for bar in _bars([0.001 * ((-1) ** i) for i in range(40)]):
        eye.on_bar_close(bar)
    win = None
    for i in range(MIN_WINDOWS):
        win = eye.observe_window(make_window(trades=quiet_prints()), touch_id=f"t{i}", now=T0)
    assert win is not None
    eye.learn(symbol="BTCUSDT", fingerprint=win.fingerprint, idea="bounce", outcome="break", ts=T0)
    store = DictStore()
    eye.save(store)
    assert set(store.rows) == {
        "oko:passport:BTCUSDT",
        "oko:weather:BTCUSDT",
        "oko:memory:BTCUSDT",
        "oko:mirror",
    }
    back = OkoEye(working_tf="15m")
    assert back.load(store) == 4
    assert back.passport_for("BTCUSDT").depth.n == MIN_WINDOWS
    assert back.weather_report("BTCUSDT") == eye.weather_report("BTCUSDT")
    assert back.memory_for("BTCUSDT").n == 1
    assert back.mirror == eye.mirror
    assert back.mirror_ok is True


def test_load_reports_bad_organs_instead_of_dying() -> None:
    """A corrupt organ must not stop the desk from starting: it is dropped and named."""
    eye = OkoEye(working_tf="15m")
    for bar in _bars([0.001] * 3):
        eye.on_bar_close(bar)
    store = DictStore()
    eye.save(store)
    other = OkoEye(working_tf="1h")
    other.load(store)
    assert "BTCUSDT" not in other.weathers
    assert any("tf" in v for v in other.load_errors.values())
    bad = DictStore()
    bad.rows["oko:liver:BTCUSDT"] = "{}"
    e2 = OkoEye(working_tf="15m")
    e2.load(bad)
    assert "organ" in e2.load_errors["oko:liver:BTCUSDT"]
    nosym = DictStore()
    nosym.rows["oko:passport"] = "{}"
    e3 = OkoEye(working_tf="15m")
    e3.load(nosym)
    assert "symbol" in e3.load_errors["oko:passport"]


def test_load_migrates_pre_footprint_memory_rows() -> None:
    """Antigens saved between 20:02 and 21:23 on 2026-09-02 carry 10 ints (Shadow only).
    They are dropped (padding would inflate the Hamming distance), counted, never a crash."""
    from capitalizator.oko.footprint import FINGERPRINT_LEN

    store = DictStore()
    store.rows["oko:memory:BTCUSDT"] = json.dumps({
        "symbol": "BTCUSDT",
        "records": [
            {"f": [1, 0, 2, 0, 0, 1, 0, 0, 3, 0], "family": "bounce", "trap": True, "ts": "2026-09-02T20:30:00+00:00"},
            {"f": [1, 0, 2, 0, 0, 1, 0, 0, 3, 0, 0, 1, 2], "family": "bounce", "trap": False, "ts": "2026-09-02T21:30:00+00:00"},
            {"f": [1, 2], "family": "bounce", "trap": False, "ts": "x"},
        ],
    })
    eye = OkoEye(working_tf="15m")
    eye.load(store)
    mem = eye.memory_for("BTCUSDT")
    # the 10-int row is counted and dropped (not comparable with 13-int probes), the
    # malformed one skipped, the 13-int one kept
    assert mem.n == 1 and mem.migrated == 1 and mem.skipped == 1
    assert all(len(r.fingerprint) == FINGERPRINT_LEN for r in mem.records)
    assert "migrated=1" in eye.load_errors["oko:memory:BTCUSDT"]



def test_save_and_load_through_knowledge(tmp_path: Path) -> None:
    knowledge = open_knowledge(init_vault(tmp_path / "desk"))
    eye = OkoEye(working_tf="15m")
    eye.observe_window(make_window(trades=quiet_prints()), touch_id="t", now=T0)
    eye.save(knowledge, symbols=("BTCUSDT",))
    assert knowledge.meta("oko:passport:BTCUSDT") is not None
    back = OkoEye(working_tf="15m")
    assert back.load(knowledge) == 1
    assert back.passport_for("BTCUSDT").depth.n == 1
    empty = open_knowledge(init_vault(tmp_path / "other"), create=False)
    assert OkoEye(working_tf="15m").load(empty) == 0


def test_on_bar_close_ignores_other_tf() -> None:
    eye = OkoEye(working_tf="15m")
    bar = _bars([0.001], tf="1h")[-1]
    assert eye.on_bar_close(bar) is None
    assert "BTCUSDT" not in eye.weathers
    bars = _bars([0.001, 0.002])
    for b in bars:
        eye.on_bar_close(b)
    assert eye.weather_for("BTCUSDT").n == 2
    assert eye.on_bar_close(bars[-1]) is None  # same close already seen
    assert eye.weather_for("BTCUSDT").n == 2
