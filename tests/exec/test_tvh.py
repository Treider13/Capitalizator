"""TVH is a skip, not a voice. Unknown tape or thin n is no_tvh."""

from __future__ import annotations

import inspect

from capitalizator.exec.tvh import NO_TVH, tvh_ok
from capitalizator.jury import desk


def test_ready_reject_and_tape_is_tvh() -> None:
    assert (
        tvh_ok(
            price_in_zone=True,
            mid=False,
            cav="REJECT",
            zlg="DEFEND",
            n_cav=20,
            n_zlg=20,
            tape_eaten=False,
        )
        is True
    )


def test_unknown_tape_is_not_tvh() -> None:
    assert (
        tvh_ok(
            price_in_zone=True,
            mid=False,
            cav="REJECT",
            zlg="DEFEND",
            n_cav=20,
            n_zlg=20,
            tape_eaten=None,
        )
        is False
    )


def test_mid_range_is_not_tvh() -> None:
    assert (
        tvh_ok(
            price_in_zone=True,
            mid=True,
            cav="REJECT",
            zlg="DEFEND",
            n_cav=20,
            n_zlg=20,
            tape_eaten=False,
        )
        is False
    )


def test_thin_n_is_not_tvh() -> None:
    assert (
        tvh_ok(
            price_in_zone=True,
            mid=False,
            cav="REJECT",
            zlg="DEFEND",
            n_cav=19,
            n_zlg=19,
            tape_eaten=False,
        )
        is False
    )


def test_tvh_is_invisible_to_jury() -> None:
    src = inspect.getsource(desk)
    assert "no_tvh" not in src
    assert "tvh_ok" not in src
    assert NO_TVH == "no_tvh"
