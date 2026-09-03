"""Weather: UNKNOWN before 30 bars; RANGE on iid noise; TRANSITION → VOL_EXPANSION
on a variance jump; TREND on drift; replay from dict is the same posterior."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.oko.weather import MAX_RUN, MIN_BARS, Weather
from capitalizator.zones.model import Bar

START = datetime(2026, 8, 1, tzinfo=UTC)


def _bars(returns: list[float], *, symbol: str = "BTCUSDT", tf: str = "15m") -> list[Bar]:
    px = 100.0
    out: list[Bar] = []
    for i, r in enumerate([0.0, *returns]):
        px *= math.exp(r)
        close_ts = START + timedelta(minutes=15 * (i + 1))
        d = Decimal(f"{px:.6f}")
        out.append(
            Bar(
                symbol=symbol,
                tf=tf,
                open_ts=close_ts - timedelta(minutes=15),
                close_ts=close_ts,
                open=d,
                high=d,
                low=d,
                close=d,
            )
        )
    return out


def _feed(returns: list[float]) -> Weather:
    w = Weather("BTCUSDT", tf="15m")
    for bar in _bars(returns):
        w.update(bar)
    return w


def test_unknown_before_min_bars() -> None:
    rng = random.Random(1)
    w = _feed([rng.gauss(0, 0.002) for _ in range(MIN_BARS - 1)])
    rep = w.report()
    assert rep.regime == "UNKNOWN"
    assert rep.n_bars == MIN_BARS - 1
    assert rep.cp_prob is not None  # posterior exists after WARMUP, label does not


def test_iid_noise_is_mostly_range_with_low_cp() -> None:
    """A random walk can show a local drift (seed 2 does: t≈3.9 on 30 bars).
    The law is: no changepoint mass, and RANGE in the clear majority of seeds."""
    labels: list[str] = []
    for seed in range(1, 8):
        rng = random.Random(seed)
        rep = _feed([rng.gauss(0, 0.002) for _ in range(120)]).report()
        labels.append(rep.regime)
        assert rep.cp_prob is not None and rep.cp_prob < 0.3
        assert rep.regime in {"RANGE", "TREND"}
    assert labels.count("RANGE") >= 5
    rng = random.Random(1)
    one = _feed([rng.gauss(0, 0.002) for _ in range(120)]).report()
    assert one.regime == "RANGE"
    assert one.run_n == 120


def test_variance_jump_is_seen_then_named_expansion() -> None:
    rng = random.Random(3)
    calm = [rng.gauss(0, 0.001) for _ in range(80)]
    wild = [rng.gauss(0, 0.006) for _ in range(25)]
    w = Weather("BTCUSDT", tf="15m")
    labels: list[str] = []
    cps: list[float] = []
    for bar in _bars(calm + wild):
        w.update(bar)
        rep = w.report()
        labels.append(rep.regime)
        cps.append(rep.cp_prob if rep.cp_prob is not None else 0.0)
    assert labels[79] == "RANGE"
    early = labels[80:88]
    assert "TRANSITION" in early
    assert max(cps[80:88]) >= 0.5
    assert labels[-1] == "VOL_EXPANSION"
    final = w.report()
    assert final.vol_ratio is not None and final.vol_ratio >= 1.8


def test_steady_drift_is_trend() -> None:
    rng = random.Random(4)
    w = _feed([0.003 + rng.gauss(0, 0.001) for _ in range(60)])
    rep = w.report()
    assert rep.regime == "TREND"
    assert rep.run_mean is not None and rep.run_mean > 0


def test_out_of_order_duplicate_and_foreign_bars_are_ignored() -> None:
    w = Weather("BTCUSDT", tf="15m")
    bars = _bars([0.001, 0.002, -0.001])
    for bar in bars:
        w.update(bar)
    assert w.n == 3
    assert w.update(bars[1]) is None
    assert w.n == 3
    other_tf = _bars([0.01], tf="1h")[-1]
    assert w.update(other_tf) is None
    other_symbol = _bars([0.01], symbol="ETHUSDT")[-1]
    assert w.update(other_symbol) is None
    assert w.n == 3


def test_replay_from_dict_reproduces_the_posterior() -> None:
    rng = random.Random(5)
    w = _feed([rng.gauss(0.0005, 0.002) for _ in range(150)])
    back = Weather.from_dict(w.to_dict())
    assert back.report() == w.report()
    assert back.last_close == w.last_close
    assert back.last_close_ts == w.last_close_ts
    # And it keeps ignoring the bar it already saw.
    last = _bars([rng.gauss(0, 0.002) for _ in range(150)])[-1]
    assert back.update(last) is None


def test_run_length_is_truncated_and_normalised() -> None:
    rng = random.Random(6)
    w = _feed([rng.gauss(0, 0.002) for _ in range(MAX_RUN + 200)])
    assert len(w._log_r) == MAX_RUN
    assert abs(sum(math.exp(v) for v in w._log_r) - 1.0) < 1e-9
    assert w.report().regime == "RANGE"


def test_rejects_bad_construction_and_close() -> None:
    with pytest.raises(ValueError):
        Weather("", tf="15m")
    with pytest.raises(ValueError):
        Weather("BTCUSDT", tf="15m", hazard_lambda=1.0)
    w = Weather("BTCUSDT", tf="15m")
    bad = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=START,
        close_ts=START + timedelta(minutes=15),
        open=Decimal("0"),
        high=Decimal("0"),
        low=Decimal("0"),
        close=Decimal("0"),
    )
    with pytest.raises(ValueError):
        w.update(bad)
    with pytest.raises(ValueError):
        Weather.from_dict({"symbol": "X", "tf": "15m", "returns": "no"})
