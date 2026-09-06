"""D1 point-in-time levels, directional room and production data/UI wiring."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from tests.fusion.daily_fixtures import daily_rows, seed_daily
from tests.fusion.test_contract_runtime import account, block, contract, instrument, register
from tests.fusion.test_cross_market import frame
from tests.fusion.test_review import PRICES, make_bars

from capitalizator.fusion.atlas import Forecast
from capitalizator.fusion.config import Config
from capitalizator.fusion.contracts import propose
from capitalizator.fusion.daily import DAY_SECONDS, daily_context, daily_target
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.market import Market
from capitalizator.fusion.runtime import Runtime
from capitalizator.fusion.store import Store
from capitalizator.fusion.structure import TFS, Structure, parse_history

NOW = 20 * DAY_SECONDS + 10


def context(at=NOW, low=50, high=150):
    market = Market("BTCUSDT", Config())
    seed_daily(market, at, low, high)
    return daily_context(market.structure.cache["1d"], 100, at)


def candidate(side=1, daily=None):
    b = block(at=NOW, close=100)
    c = {
        **b.context,
        "sweep": side,
        "sweep_extreme": 99 if side == 1 else 101,
        "ask": 100.01,
        "bid": 100,
        "daily": context() if daily is None else daily,
        "pairing": {
            "allowed": True,
            "retracement": 0.75,
            "target": 130 if side == 1 else 70,
            "regime": "trend",
        },
    }
    f = Forecast(
        "fixture",
        ((side * 0.01, 0.5, 0.2, 10),) * 3,
        ((side * 0.01, 0.5, 0.2, 10),) * 20,
        -0.0001,
        0.0001,
        0,
        False,
    )
    return propose("BTCUSDT", replace(b, context=c), f, Config(), 0.001, 0.01)


def test_daily_history_excludes_open_day_and_does_not_aggregate_partial_startup_day():
    rows = daily_rows(NOW)
    rows.append([str(20 * DAY_SECONDS * 1000), "100", "999", "1", "100", "10"])
    closed = parse_history("BTCUSDT", "1d", rows, NOW)
    assert len(closed) == 5
    market = Market("BTCUSDT", Config())
    market.ingest("history", {"tf": "1d", "rows": rows}, NOW)
    assert "1d" not in market.builder.tfs
    assert "1d" in market.structure.cache
    daily = daily_context(market.structure.cache["1d"], 100, NOW)
    assert daily["status"] == "ready"
    assert daily["support"]["price"] == 50
    assert daily["resistance"]["price"] == 150
    assert {p["kind"] for p in daily["levels"]} == {"previous_day_high", "previous_day_low"}


def test_daily_pivot_only_exists_after_two_right_closed_days_and_no_history_repaint():
    s = Structure()
    bars = make_bars("1d", DAY_SECONDS, PRICES, end=20 * DAY_SECONDS)
    s.seed(bars[:13], 0.01)
    before = s.cache["1d"]
    pivot_at = bars[12].open_ts.timestamp()
    assert not any(p["at"] == pivot_at for p in before["highs"])
    s.seed(bars[13:15], 0.01)
    confirmed = next(p for p in s.cache["1d"]["highs"] if p["at"] == pivot_at)
    assert confirmed["known_at"] == bars[14].close_ts.timestamp()
    assert not any(p["at"] == pivot_at for p in before["highs"])


def test_nearest_level_is_selected_across_both_pivot_types_and_previous_day():
    s = Structure()
    s.seed(make_bars("1d", DAY_SECONDS, PRICES, end=20 * DAY_SECONDS), 0.01)
    d = daily_context(s.cache["1d"], 110, NOW)
    assert d["resistance"]["price"] == 111  # Previous day high is before swing high 117.
    assert d["support"]["price"] == 109
    assert d["support"]["known_at"] <= d["at"]


@pytest.mark.parametrize(
    "offset,status",
    [(0, "ready"), (DAY_SECONDS - 1, "ready"), (DAY_SECONDS, "stale"), (-1, "stale")],
)
def test_daily_validity_changes_exactly_at_utc_boundary(offset, status):
    s = Structure()
    s.seed(parse_history("BTCUSDT", "1d", daily_rows(NOW), NOW), 0.01)
    assert daily_context(s.cache["1d"], 100, 20 * DAY_SECONDS + offset)["status"] == status


def test_gap_requires_five_contiguous_days_and_rest_repair_restores_context():
    s = Structure()
    rows = daily_rows(NOW)
    s.seed(parse_history("BTCUSDT", "1d", rows[:2] + rows[3:], NOW), 0.01)
    assert daily_context(s.cache["1d"], 100, NOW)["status"] == "warming"
    s.seed(parse_history("BTCUSDT", "1d", rows, NOW), 0.01)
    assert daily_context(s.cache["1d"], 100, NOW)["status"] == "ready"


@pytest.mark.parametrize("side", [1, -1])
def test_daily_obstacle_caps_target_without_changing_invalidation(side):
    unrestricted, _ = candidate(side)
    daily = context(low=80, high=120)
    capped, reason = candidate(side, daily)
    assert reason == "candidate" and capped is not None and unrestricted is not None
    assert capped.target == pytest.approx(120 - 0.01 if side == 1 else 80 + 0.01)
    assert capped.invalidation == unrestricted.invalidation
    assert capped.definition["daily_check"]["limited"]
    assert capped.definition["daily"]["at"] == 20 * DAY_SECONDS


@pytest.mark.parametrize("side", [1, -1])
def test_daily_level_too_close_rejects_entry(side):
    c, reason = candidate(side, context(low=99, high=101))
    assert c is None and reason == "insufficient_daily_room"


@pytest.mark.parametrize(
    "daily,reason",
    [
        ({}, "daily_context_missing"),
        ({"status": "warming"}, "daily_context_warming"),
        ({"status": "stale"}, "daily_context_stale"),
    ],
)
def test_unavailable_daily_context_does_not_allow_candidate(daily, reason):
    assert candidate(daily=daily) == (None, reason)


def test_target_beyond_all_known_levels_is_not_invented_or_extended():
    d = context()
    check = daily_target(d, 1, 160, 170, 0.01, NOW)
    assert check["allowed"] and not check["limited"] and check["level"] is None
    assert check["target"] == 170
    assert daily_target(d, 1, 150, 170, 0.01, NOW)["target"] == 149.99
    assert not daily_target(d, 1, 100, 120, 0.01, 21 * DAY_SECONDS)["allowed"]


@pytest.mark.parametrize("ready", [True, False])
def test_confirmation_rejects_new_obstacle_or_missing_daily_data(tmp_path, ready):
    store = Store(tmp_path / "db")
    try:
        engine = Engine("BTCUSDT", store, Shared(), Config(), variant="B")
        engine.contract = contract()
        register(store, engine.contract)
        account(store)
        engine.market.ingest("book", frame(qty=2000), 101)
        engine.market.ingest("ticker", {"data": {}}, 101)
        engine.market.ingest("spot_book", frame(qty=2), 101)
        if ready:
            seed_daily(engine.market, high=110)
        original = engine.contract.payload()
        engine._reserve_entry(block(), None, instrument(), "demo", True, 0.001)
        assert engine.contract_state == "expired"
        assert not store.rows("SELECT * FROM orders")
        reason = "daily_level_changed_after_confirmation" if ready else "daily_context_warming"
        assert reason in store.rows("SELECT body FROM decisions")[-1]["body"]
        assert engine.contract.payload() == original
    finally:
        store.close()


def test_unchanged_or_other_timeframe_history_does_not_recalculate_daily_levels():
    s = Structure()
    bars = parse_history("BTCUSDT", "1d", daily_rows(NOW), NOW)
    s.seed(bars, 0.01)
    daily, revision = s.cache["1d"], s.revision
    s.seed(bars, 0.01)
    assert s.revision == revision
    s.seed(make_bars("1m", 60, PRICES), 0.01)
    assert s.cache["1d"] is daily and s.revision == revision + 1


def test_history_worker_requests_D_and_chart_exposes_daily_on_every_timeframe(tmp_path):
    runtime = Runtime(tmp_path, Config())
    calls = []

    def get(path, params, timeout):
        calls.append(params)
        return {"list": daily_rows(NOW) if params["interval"] == "D" else [], "_known_at": NOW}

    try:
        with (
            patch("capitalizator.fusion.runtime.public_get", get),
            patch.object(
                runtime.supervisor.stop, "wait", side_effect=lambda _: runtime.supervisor.stop.set()
            ),
            patch("capitalizator.fusion.runtime.time.time", return_value=NOW),
        ):
            runtime._history()
            assert {p["interval"] for p in calls} == {"1", "5", "15", "60", "240", "D"}
            assert {p["symbol"] for p in calls if p["interval"] == "D"} == set(
                runtime.config.symbols
            )
            for mailbox in runtime.mailboxes:
                for symbol, kind, frame, at, _ in mailbox.get(0):
                    runtime.engines[symbol].process(kind, frame, at)
            for tf in TFS:
                chart = runtime.chart("BTCUSDT", tf)
                assert chart["daily"]["status"] == "ready"
                if tf == "1d":
                    assert len(chart["candles"]) == 5 and chart["forming"] is None
    finally:
        runtime.store.close()
