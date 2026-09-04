"""Э3 — calibration class includes the zone TF. A 15m REJECT is not a 4h REJECT."""

from __future__ import annotations

from capitalizator.champion.calibrate import (
    class_key,
    class_stats,
    legacy_key,
    lookup,
    tf_key,
    window_key,
    window_tf_key,
)


def _row(r: str, *, tf: str, window: str = "overlap", group: str = "majors") -> dict:
    return {
        "tag": "bounce",
        "entry_px": "100",
        "r_net": r,
        "labels": {
            "cav_label": "REJECT",
            "zlg_label": "DEFEND",
            "window": window,
            "symbol_group": group,
            "zone_tf": tf,
        },
    }


def test_class_key_is_six_parts_with_tf() -> None:
    full = class_key(
        idea="bounce", cav="REJECT", zlg="DEFEND", window="asia", group="rest", tf="4h"
    )
    assert full == "bounce|REJECT|DEFEND|asia|rest|4h"
    assert window_tf_key(full) == "bounce|REJECT|DEFEND|asia|*|4h"
    assert tf_key(full) == "bounce|REJECT|DEFEND|*|*|4h"
    assert window_key(full) == "bounce|REJECT|DEFEND|asia|*|*"
    assert legacy_key(full) == "bounce|REJECT|DEFEND|*|*|*"
    assert class_key(idea="bounce", cav="REJECT", zlg="DEFEND") == "bounce|REJECT|DEFEND|*|*|*"


def test_15m_and_4h_are_different_classes() -> None:
    rows = [_row("1", tf="15m")] * 10 + [_row("-1", tf="4h")] * 10
    stats = class_stats(rows)
    m15 = stats["bounce|REJECT|DEFEND|overlap|majors|15m"]
    h4 = stats["bounce|REJECT|DEFEND|overlap|majors|4h"]
    assert m15.n == 10 and m15.wins == 10
    assert h4.n == 10 and h4.wins == 0
    # collapsed window still sees both
    assert stats["bounce|REJECT|DEFEND|overlap|*|*"].n == 20
    # TF aggregate keeps them apart
    assert stats["bounce|REJECT|DEFEND|*|*|15m"].n == 10
    assert stats["bounce|REJECT|DEFEND|*|*|4h"].n == 10


def test_lookup_falls_back_along_tf_then_window() -> None:
    # 10 majors 15m (thin) + 25 top10 15m → window+tf has 35
    rows = [_row("-1", tf="15m")] * 10 + [_row("1", tf="15m", group="top10")] * 25
    rows += [_row("1", tf="4h")] * 40  # a different TF must not leak into the 15m lookup
    stats = class_stats(rows)
    key = "bounce|REJECT|DEFEND|overlap|majors|15m"
    got = lookup(stats, key)
    assert got is not None
    assert got.key == window_tf_key(key)
    assert got.n == 35
    assert lookup(stats, "bounce|REJECT|DEFEND|overlap|majors|4h").n == 40


def test_old_five_part_key_is_tf_star() -> None:
    """Journal rows written before zone_tf still feed the legacy aggregate."""
    row = {
        "tag": "bounce",
        "entry_px": "1",
        "r_net": "1",
        "labels": {"cav_label": "REJECT", "zlg_label": "DEFEND", "window": "asia",
                   "symbol_group": "majors"},
    }
    stats = class_stats([row])
    assert "bounce|REJECT|DEFEND|asia|majors|*" in stats
    assert stats["bounce|REJECT|DEFEND|*|*|*"].n == 1
    assert window_key("bounce|REJECT|DEFEND|asia|majors") == "bounce|REJECT|DEFEND|asia|*|*"
