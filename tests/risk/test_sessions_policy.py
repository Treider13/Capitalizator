"""SessionPolicy: windows tile the day, blackouts, weekend, funding, symbols, 5x."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.news_macro.ingest import NewsRow
from capitalizator.risk.sessions import (
    SessionPolicy,
    SessionPolicyError,
    coverage_check,
    load_policy_yaml,
)


@pytest.fixture(scope="module")
def raw() -> dict:
    return load_policy_yaml()


@pytest.fixture(scope="module")
def policy(raw: dict) -> SessionPolicy:
    return SessionPolicy(raw)


def _mon(h: int, m: int = 0) -> datetime:
    # 2026-01-05 is a Monday.
    return datetime(2026, 1, 5, h, m, tzinfo=UTC)


def test_repo_yaml_loads_and_tiles_the_day(policy: SessionPolicy) -> None:
    assert coverage_check(policy) == 1440
    assert policy.names() == ("asia", "europe", "overlap", "us", "night", "weekend")
    assert policy.daily_budget_cap() == 21


@pytest.mark.parametrize(
    ("h", "m", "name"),
    [
        (0, 0, "asia"),
        (6, 59, "asia"),
        (7, 0, "europe"),
        (11, 59, "europe"),
        (12, 0, "overlap"),
        (16, 29, "overlap"),
        (16, 30, "us"),
        (20, 59, "us"),
        (21, 0, "night"),
        (23, 59, "night"),
    ],
)
def test_window_boundaries(policy: SessionPolicy, h: int, m: int, name: str) -> None:
    assert policy.window(_mon(h, m)).name == name


def test_naive_datetime_is_refused(policy: SessionPolicy) -> None:
    with pytest.raises(TypeError):
        policy.window(datetime(2026, 1, 5, 12, 0))


def test_overlap_allows_full_size_and_5x(policy: SessionPolicy) -> None:
    ok, why = policy.allows(_mon(13, 0), idea="bounce", symbol="SOLUSDT", lev=Decimal("5"))
    assert ok and why == "window:overlap"
    st = policy.window(_mon(13, 0))
    assert st.size_mult == Decimal("1.0") and st.k_atr == Decimal("0.5") and st.budget == 8


def test_5x_outside_overlap_is_refused(policy: SessionPolicy) -> None:
    ok, why = policy.allows(_mon(9, 0), idea="bounce", symbol="BTCUSDT", lev=Decimal("5"))
    assert not ok and why == "window:europe:no_5x"


def test_night_is_closed(policy: SessionPolicy) -> None:
    ok, why = policy.allows(_mon(22, 0), idea="bounce", symbol="BTCUSDT")
    assert not ok and why == "window:night:closed"


def test_asia_refuses_breakout_and_cuts_size(policy: SessionPolicy) -> None:
    ok, why = policy.allows(_mon(1, 0), idea="breakout", symbol="BTCUSDT")
    assert not ok and why == "window:asia:idea:breakout"
    ok, why = policy.allows(_mon(1, 0), idea="bounce", symbol="BTCUSDT")
    assert ok
    st = policy.window(_mon(1, 0))
    assert st.size_mult == Decimal("0.5") and st.k_atr == Decimal("0.8")


def test_daily_open_blackout_for_everyone(policy: SessionPolicy) -> None:
    ok, why = policy.allows(_mon(0, 10), idea="bounce", symbol="BTCUSDT")
    assert not ok and why == "blackout:daily_open"
    ok, _ = policy.allows(_mon(0, 15), idea="bounce", symbol="BTCUSDT")
    assert ok


def test_asia_thin_hours_block_alts_not_majors(policy: SessionPolicy) -> None:
    rank = {"SOLUSDT": 3}
    ok, why = policy.allows(_mon(3, 0), idea="bounce", symbol="SOLUSDT", rank=rank)
    assert not ok and why == "blackout:asia_thin_alts"
    ok, _ = policy.allows(_mon(3, 0), idea="bounce", symbol="ETHUSDT")
    assert ok


def test_us_equity_close_blackout(policy: SessionPolicy) -> None:
    ok, why = policy.allows(_mon(19, 50), idea="bounce", symbol="BTCUSDT")
    assert not ok and why == "blackout:us_equity_close"


def test_cme_maintenance_only_on_sunday(policy: SessionPolicy) -> None:
    sunday = datetime(2026, 1, 4, 22, 30, tzinfo=UTC)
    # weekend window is open for majors, so the blackout is what refuses
    ok, why = policy.allows(sunday, idea="bounce", symbol="BTCUSDT")
    assert not ok and why == "blackout:cme_maintenance"
    saturday = datetime(2026, 1, 3, 22, 30, tzinfo=UTC)
    ok, why = policy.allows(saturday, idea="bounce", symbol="BTCUSDT")
    assert ok and why == "window:weekend"


def test_weekend_overrides_the_clock_window(policy: SessionPolicy) -> None:
    saturday_noon = datetime(2026, 1, 3, 13, 0, tzinfo=UTC)
    st = policy.window(saturday_noon)
    assert st.weekend and st.name == "weekend" and st.size_mult == Decimal("0.5")
    assert policy.clock_name(saturday_noon) == "overlap"
    ok, why = policy.allows(saturday_noon, idea="bounce", symbol="SOLUSDT", rank={"SOLUSDT": 1})
    assert not ok and why == "window:weekend:symbols:majors_only"
    ok, why = policy.allows(saturday_noon, idea="breakout", symbol="BTCUSDT")
    assert not ok and why == "window:weekend:idea:breakout"


def test_symbol_policies(policy: SessionPolicy) -> None:
    rank = {"SOLUSDT": 3, "XRPUSDT": 7, "TIAUSDT": 19}
    # asia: top5 + majors
    assert policy.allows(_mon(6, 30), idea="bounce", symbol="SOLUSDT", rank=rank)[0]
    ok, why = policy.allows(_mon(6, 30), idea="bounce", symbol="XRPUSDT", rank=rank)
    assert not ok and why == "window:asia:symbols:not_top5"
    # europe: top10 or screened
    assert policy.allows(_mon(9, 0), idea="bounce", symbol="XRPUSDT", rank=rank)[0]
    ok, why = policy.allows(_mon(9, 0), idea="bounce", symbol="TIAUSDT", rank=rank)
    assert not ok and why == "window:europe:symbols:not_top10_not_screened"
    assert policy.allows(
        _mon(9, 0), idea="bounce", symbol="TIAUSDT", rank=rank, screened=frozenset({"TIAUSDT"})
    )[0]
    # unknown rank, not major, not screened → refused; majors always pass
    ok, _ = policy.allows(_mon(9, 0), idea="bounce", symbol="NEWUSDT", rank=None)
    assert not ok
    assert policy.allows(_mon(9, 0), idea="bounce", symbol="BTCUSDT", rank=None)[0]


def test_funding_settlement_blackout(policy: SessionPolicy) -> None:
    now = _mon(13, 0)
    ok, why = policy.allows(
        now, idea="bounce", symbol="BTCUSDT", next_funding_at=now + timedelta(minutes=4)
    )
    assert not ok and why == "funding_settlement"
    ok, _ = policy.allows(
        now, idea="bounce", symbol="BTCUSDT", next_funding_at=now + timedelta(minutes=6)
    )
    assert ok
    # a settlement that just passed is symmetric
    ok, why = policy.allows(
        now, idea="bounce", symbol="BTCUSDT", next_funding_at=now - timedelta(minutes=3)
    )
    assert not ok and why == "funding_settlement"


def test_us_data_day_blocks_only_configured_windows(policy: SessionPolicy) -> None:
    cpi = NewsRow(
        event_id="cpi-2026-01",
        event_class="CPI",
        event_time=datetime(2026, 1, 5, 13, 30, tzinfo=UTC),
        known_at=datetime(2025, 12, 1, tzinfo=UTC),
        assets=("BTCUSDT",),
        source="bls",
        announce_tz="America/New_York",
        size_rule="",
        notes="",
        raw="",
    )
    # 01:00Z is still Jan 4 in New York → not a US-data day yet (NY calendar anchor).
    ok, _ = policy.allows(_mon(1, 0), [cpi], idea="bounce", symbol="BTCUSDT")
    assert ok
    # 06:00Z = 01:00 EST Jan 5 → US-data day, asia is blocked.
    ok, why = policy.allows(_mon(6, 0), [cpi], idea="bounce", symbol="BTCUSDT")
    assert not ok and why == "us_data_day:asia"
    ok, _ = policy.allows(_mon(6, 0), [cpi], idea="bounce", symbol="BTCUSDT", no_us_today=True)
    assert ok
    # europe is not in us_data_day_block_windows: MacroRules pre-event ×0.5 applies there
    ok, _ = policy.allows(_mon(9, 0), [cpi], idea="bounce", symbol="BTCUSDT")
    assert ok


def test_budget_key_is_utc_date_and_window(policy: SessionPolicy) -> None:
    assert policy.window(_mon(9, 0)).budget_key == "2026-01-05:europe"
    saturday = datetime(2026, 1, 3, 13, 0, tzinfo=UTC)
    assert policy.window(saturday).budget_key == "2026-01-03:weekend"


# --- validation ------------------------------------------------------------------------


def test_unknown_key_is_refused(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["extra"] = 1
    with pytest.raises(SessionPolicyError):
        SessionPolicy(bad)


def test_gap_between_windows_is_refused(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["windows"]["europe"]["start"] = "07:30"
    with pytest.raises(SessionPolicyError, match="gap or overlap"):
        SessionPolicy(bad)


def test_last_window_must_end_at_midnight(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["windows"]["night"]["end"] = "23:00"
    with pytest.raises(SessionPolicyError, match="24:00"):
        SessionPolicy(bad)


def test_size_mult_above_one_is_refused(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["windows"]["overlap"]["size_mult"] = "1.5"
    with pytest.raises(SessionPolicyError, match="outside"):
        SessionPolicy(bad)


def test_unknown_idea_is_refused(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["windows"]["overlap"]["ideas"] = ["bounce", "grid"]
    with pytest.raises(SessionPolicyError, match="unknown ideas"):
        SessionPolicy(bad)


def test_non_utc_tz_is_refused(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["tz"] = "Europe/Moscow"
    with pytest.raises(SessionPolicyError, match="UTC"):
        SessionPolicy(bad)


def test_weekly_blackout_needs_weekday(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["blackouts"].append(
        {"name": "x", "kind": "weekly", "start": "01:00", "end": "02:00", "applies_to": "all"}
    )
    with pytest.raises(SessionPolicyError, match="weekday"):
        SessionPolicy(bad)


def test_unknown_us_data_block_window_is_refused(raw: dict) -> None:
    bad = copy.deepcopy(raw)
    bad["us_data_day_block_windows"] = ["mars"]
    with pytest.raises(SessionPolicyError, match="unknown windows"):
        SessionPolicy(bad)
