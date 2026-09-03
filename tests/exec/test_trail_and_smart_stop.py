"""§6 smart stop + §7 trail engine: monotone, structure-based, venue trailing on spikes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.exec.paper import PaperEngine
from capitalizator.exec.smart_stop import (
    initial_stop,
    push_past_clusters,
    round_levels_near,
    soft_exit,
)
from capitalizator.exec.trail import TrailEngine, TrailState
from capitalizator.patterns.bar_quality import atr as atr_of
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _bar(i: int, o: str, h: str, l: str, c: str) -> Bar:  # noqa: E741
    start = T0 + timedelta(minutes=15 * i)
    return Bar(symbol="BTCUSDT", tf="15m", open_ts=start, close_ts=start + timedelta(minutes=15),
               open=Decimal(o), high=Decimal(h), low=Decimal(l), close=Decimal(c),
               volume=Decimal("10"))


# --- smart stop -------------------------------------------------------------------
def test_structural_mode_is_the_legacy_stop() -> None:
    got = initial_stop(side="buy", structural=Decimal("99.2"), tick=Decimal("0.1"),
                       atr=Decimal("2"), spread=Decimal("0.1"), mode="structural")
    assert got.stop == Decimal("99.2") and got.buffer == 0 and not got.moved_for_cluster


def test_volatility_buffer_is_max_of_k_atr_spread_tick_and_never_tighter() -> None:
    got = initial_stop(side="buy", structural=Decimal("99.2"), tick=Decimal("0.1"),
                       atr=Decimal("2"), spread=Decimal("0.1"), mode="volatility")
    assert got.buffer == Decimal("1.0")  # 0.5 × ATR 2 > 3 × spread 0.3 > tick
    assert got.stop == Decimal("98.2")
    short = initial_stop(side="sell", structural=Decimal("101"), tick=Decimal("0.1"),
                         atr=None, spread=Decimal("0.2"), mode="volatility")
    assert short.stop == Decimal("101.6")  # 3 × spread
    assert short.components["structural"] == "101"


def test_hybrid_pushes_the_stop_past_a_round_number_and_a_zone_edge() -> None:
    # structural 100.4, tick 0.1, ATR None, spread 0.1 → buffer 0.3 → 100.1; round 100 is
    # within 5 ticks → push below 100 − 0.5 = 99.5
    got = initial_stop(side="buy", structural=Decimal("100.4"), tick=Decimal("0.1"),
                       atr=None, spread=Decimal("0.1"), mode="hybrid")
    assert got.moved_for_cluster and got.stop == Decimal("99.5")
    assert got.components["cluster_level"] == "100"
    other = Zone.create(symbol="BTCUSDT", tf="15m", side="support", lo=Decimal("99.3"),
                        hi=Decimal("99.6"), method="swing", created_as_of=T0)
    got2 = initial_stop(side="buy", structural=Decimal("100.4"), tick=Decimal("0.1"),
                        atr=None, spread=Decimal("0.1"), zones=[other], mode="hybrid")
    assert got2.stop < Decimal("99.3")  # pushed past the other zone too
    sell = initial_stop(side="sell", structural=Decimal("99.6"), tick=Decimal("0.1"),
                        atr=None, spread=Decimal("0.1"), mode="hybrid")
    assert sell.moved_for_cluster and sell.stop == Decimal("100.5")


def test_round_levels_scale_with_price() -> None:
    assert Decimal("100") in round_levels_near(Decimal("100.2"), span=Decimal("0.5"))
    assert Decimal("65000") in round_levels_near(Decimal("64990"), span=Decimal("50"))
    assert Decimal("0.5") in round_levels_near(Decimal("0.53"), span=Decimal("0.05"))
    assert Decimal("100") in round_levels_near(Decimal("99.9"), span=Decimal("0.5"))


def test_soft_exit_is_close_based() -> None:
    assert soft_exit(side="buy", structural=Decimal("99"), bar=_bar(0, "100", "101", "98", "98.5"))
    assert not soft_exit(side="buy", structural=Decimal("99"), bar=_bar(0, "100", "101", "98", "99.5"))
    assert soft_exit(side="sell", structural=Decimal("101"), bar=_bar(0, "100", "102", "99", "101.5"))


def test_bad_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        initial_stop(side="long", structural=Decimal("1"), tick=Decimal("0.1"), atr=None, spread=None)
    with pytest.raises(ValueError):
        initial_stop(side="buy", structural=Decimal("0.1"), tick=Decimal("0.1"), atr=Decimal("5"),
                     spread=None, mode="volatility")


# --- trail engine -------------------------------------------------------------------
# Lows with two confirmed Williams fractals (n=2): 99.9 at i=4 and 100.9 at i=9.
_LOWS = ["100", "100.4", "100.8", "100.2", "99.9", "100.5", "101.0", "101.6", "101.1",
         "100.9", "101.5", "102.0"]


def _uptrend(n: int = 12) -> list[Bar]:
    bars = []
    for i in range(n):
        lo = Decimal(_LOWS[i % len(_LOWS)]) + Decimal(i // len(_LOWS)) * 3
        bars.append(_bar(i, str(lo + Decimal("0.3")), str(lo + Decimal("1.2")), str(lo),
                         str(lo + 1)))
    return bars


def test_no_trail_before_half_then_structure_trail_monotone() -> None:
    eng = TrailEngine(mode="structure")
    st = TrailState(side="buy", entry=Decimal("100"), stop=Decimal("98"), tick=Decimal("0.1"))
    bars = _uptrend(16)  # ≥15 closed bars so ATR exists
    assert eng.on_bar(st, bars, last_px=Decimal("107")) == []  # phase 0: hard stop only
    eng.on_half(st)
    actions = eng.on_bar(st, bars, last_px=Decimal("107"))
    assert len(actions) == 1 and actions[0].kind == "amend_stop"
    assert actions[0].new_stop is not None and actions[0].new_stop > Decimal("98")
    assert st.phase == 2 and st.last_swing == Decimal("100.9")  # last CONFIRMED low (i=9)
    first = st.stop
    buffer = (Decimal("0.5") * atr_of(bars) / Decimal("0.1")).to_integral_value(
        rounding="ROUND_CEILING"
    ) * Decimal("0.1")
    raw = TrailEngine._round(Decimal("100.9") - buffer, Decimal("0.1"), "buy")
    expected, _, _ = push_past_clusters(
        side="buy", stop=raw, tick=Decimal("0.1"), atr=atr_of(bars),
    )
    assert first == expected  # swing − k·ATR, then past magnets
    # same bars again → no move (monotone / idempotent)
    assert eng.on_bar(st, bars, last_px=Decimal("107")) == []
    assert st.stop == first
    # a new higher confirmed low → stop rises; never falls
    more = bars + [_bar(16, "106", "107", "105.6", "106.8"), _bar(17, "106.8", "107.5", "105.9", "107.2"),
                   _bar(18, "107.2", "108", "106.4", "107.8"), _bar(19, "107.8", "108.5", "106.9", "108.3")]
    eng.on_bar(st, more, last_px=Decimal("108.3"))
    assert st.last_swing == Decimal("103.2")  # i=15 confirmed once bars 16/17 closed
    assert st.stop > first
    for prev, nxt, _why in st.moves:
        assert Decimal(nxt) > Decimal(prev)
    assert st.r_px() == Decimal("2")  # 1R never changes


def test_trail_never_places_stop_above_last_price() -> None:
    eng = TrailEngine(mode="structure")
    st = TrailState(side="buy", entry=Decimal("100"), stop=Decimal("98"), tick=Decimal("0.1"))
    eng.on_half(st)
    bars = _uptrend(16)
    # price already collapsed below the swing: a stop at the swing would fire instantly → skip
    assert eng.on_bar(st, bars, last_px=Decimal("99")) == []
    assert st.stop == Decimal("98")


def test_short_side_trails_down() -> None:
    eng = TrailEngine(mode="structure")
    st = TrailState(side="sell", entry=Decimal("100"), stop=Decimal("102"), tick=Decimal("0.1"))
    eng.on_half(st)
    bars = []
    for i in range(16):
        lo_i = Decimal(_LOWS[i % len(_LOWS)]) + Decimal(i // len(_LOWS)) * 3
        hi = Decimal("200") - lo_i  # mirror of the long fixture
        bars.append(_bar(i, str(hi - Decimal("0.3")), str(hi), str(hi - Decimal("1.2")), str(hi - 1)))
    actions = eng.on_bar(st, bars, last_px=Decimal("93"))
    assert actions and actions[0].new_stop < Decimal("102")
    assert all(Decimal(n) < Decimal(p) for p, n, _ in st.moves)


def test_v_spike_arms_exchange_trailing_and_paper_follows_it() -> None:
    """Stage 4 scenario: +15% spike bar then a −5% pullback. The venue-side trailing
    stop (armed on the impulse bar) locks most of the spike without a bar close."""
    eng = TrailEngine(mode="both", impulse_mult=Decimal("2"), trail_mult=Decimal("1"))
    st = TrailState(side="buy", entry=Decimal("100"), stop=Decimal("98"), tick=Decimal("0.1"))
    eng.on_half(st)
    calm = _uptrend(16)  # ATR ≈ 1.2–1.5
    spike = _bar(16, "106", "121.9", "105.9", "121")  # range ~16 ≫ 2·ATR
    actions = eng.on_bar(st, calm + [spike], last_px=Decimal("121"))
    kinds = [a.kind for a in actions]
    assert "exchange_trailing" in kinds
    trailing = next(a for a in actions if a.kind == "exchange_trailing")
    assert trailing.trailing_distance is not None and trailing.active_price == Decimal("121")
    assert st.exchange_trailing_armed
    # second impulse does not re-arm
    assert all(a.kind != "exchange_trailing" for a in eng.on_bar(st, calm + [spike], last_px=Decimal("121")))
    # paper: arm at distance d, print at 121 then pullback to 115 → stop = 121 − d hit
    paper = PaperEngine()
    pos = paper.submit(paper_id="p", touch_id="t", symbol="BTCUSDT", side="buy",
                       limit_px=Decimal("100"), qty=Decimal("1"), stop=Decimal("98"), tp=None,
                       tick=Decimal("0.1"), now=T0, valid_for=timedelta(hours=1), source="shadow",
                       tag="bounce")

    def pr(ts, px):
        return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT", exchange_ts=ts,
                           recv_ts=ts, payload={"px": px, "qty": "1", "side": "sell"})

    paper.on_print(pr(T0 + timedelta(seconds=1), "99.9"))
    paper.on_print(pr(T0 + timedelta(minutes=1), "121"))
    assert paper.arm_trailing("p", trailing.trailing_distance, reason="impulse")
    assert pos.stop == Decimal("121") - trailing.trailing_distance
    paper.on_print(pr(T0 + timedelta(minutes=2), "123"))  # new high → stop follows up
    assert pos.stop == Decimal("123") - trailing.trailing_distance
    paper.on_print(pr(T0 + timedelta(minutes=3), "115"))  # −6.5% pullback → stopped
    assert pos.state == "closed" and pos.exit_reason == "stop"
    assert pos.exit_px >= Decimal("123") - trailing.trailing_distance - Decimal("0.1")
    assert pos.r_gross() is not None and pos.r_gross() > Decimal("5")  # most of the spike kept


def test_already_armed_trail_state_does_not_rearm() -> None:
    """Restart: twin already has trailing_distance → TrailState starts armed."""
    eng = TrailEngine(mode="both")
    st = TrailState(
        side="buy", entry=Decimal("100"), stop=Decimal("98"), tick=Decimal("0.1"),
        exchange_trailing_armed=True,
    )
    st.half_taken = True
    st.phase = 1
    spike = _bar(16, "106", "121.9", "105.9", "121")
    actions = eng.on_bar(st, _uptrend(16) + [spike], last_px=Decimal("121"))
    assert all(a.kind != "exchange_trailing" for a in actions)


def test_impulse_against_us_does_not_arm_exchange_trailing() -> None:
    eng = TrailEngine(mode="both")
    st = TrailState(side="buy", entry=Decimal("100"), stop=Decimal("98"), tick=Decimal("0.1"))
    eng.on_half(st)
    dump = _bar(16, "106", "106.2", "90", "90.5")  # range ≫ 2·ATR, close against the long
    actions = eng.on_bar(st, _uptrend(16) + [dump], last_px=Decimal("90.5"))
    assert all(a.kind != "exchange_trailing" for a in actions)
    assert not st.exchange_trailing_armed


def test_follow_trailing_does_not_place_stop_through_last_price() -> None:
    paper = PaperEngine()
    pos = paper.submit(
        paper_id="p", touch_id="t", symbol="BTCUSDT", side="buy",
        limit_px=Decimal("100"), qty=Decimal("1"), stop=Decimal("98"), tp=None,
        tick=Decimal("0.1"), now=T0, valid_for=timedelta(hours=1), source="shadow",
        tag="bounce",
    )

    def pr(ts, px):
        return MarketEvent(stream="trades", exchange="bybit", symbol="BTCUSDT",
                           exchange_ts=ts, recv_ts=ts,
                           payload={"px": px, "qty": "1", "side": "sell"})

    paper.on_print(pr(T0 + timedelta(seconds=1), "99.9"))
    paper.on_print(pr(T0 + timedelta(minutes=1), "121"))
    # spike already given back: last 115, mfe 121, distance 1 → cand 120 would fire now
    assert paper.arm_trailing("p", Decimal("1"), reason="impulse", last_px=Decimal("115"))
    assert pos.stop == Decimal("98")


def test_trail_state_rejects_wrong_side_stop() -> None:
    with pytest.raises(ValueError):
        TrailState(side="buy", entry=Decimal("100"), stop=Decimal("101"), tick=Decimal("0.1"))
    with pytest.raises(ValueError):
        TrailEngine(mode="magic")
