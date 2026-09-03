"""Э3 — MTF S/R: 15m working + 1h mid + 4h/1d HTF.

Practice this locks (not an invention): the senior TF draws the level; the next
TF down confirms the reaction; the level dies only on a close of its own TF
through the band; the band width is that TF's ATR (tick epsilon is the floor
when ATR is unmeasured).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.loop import DeskLoop
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.patterns.bar_quality import atr
from capitalizator.patterns.cav import label
from capitalizator.zones.config import load_registry
from capitalizator.zones.engine import ZONE_ATR_K, ZoneEngine
from capitalizator.zones.model import Bar, Zone
from capitalizator.zones.pair import (
    confirm_label,
    invalidated,
    junior_tf,
    pair_ready,
    vote_tf,
)

TICK = Decimal("0.1")
T0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _bar(
    tf: str,
    i: int,
    *,
    high: str,
    low: str,
    close: str,
    symbol: str = "BTCUSDT",
) -> Bar:
    minutes = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}[tf]
    open_ts = T0 + timedelta(minutes=minutes * i)
    return Bar(
        symbol=symbol,
        tf=tf,
        open_ts=open_ts,
        close_ts=open_ts + timedelta(minutes=minutes),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def _flat_series(tf: str, n: int, *, mid: str = "100", rng: str = "2") -> list[Bar]:
    half = Decimal(rng) / Decimal("2")
    px = Decimal(mid)
    return [
        _bar(tf, i, high=str(px + half), low=str(px - half), close=str(px))
        for i in range(n)
    ]


def test_registry_has_1h_between_15m_and_4h() -> None:
    cfg = load_registry()
    assert cfg.working_tf == "15m"
    assert cfg.mid_tf == "1h"
    assert cfg.htf == "4h"
    assert cfg.htf_d1 == "1d"
    assert cfg.structure_tfs == ("15m", "1h", "4h", "1d")


def test_junior_of_each_senior_is_the_next_tf_down() -> None:
    ladder = load_registry().structure_tfs
    assert junior_tf("15m", ladder) is None
    assert junior_tf("1h", ladder) == "15m"
    assert junior_tf("4h", ladder) == "1h"
    assert junior_tf("1d", ladder) == "4h"
    assert vote_tf("15m", ladder) == "15m"
    assert vote_tf("4h", ladder) == "1h"


def test_engine_draws_swings_on_1h_4h_1d() -> None:
    """Last confirmed swing exists on each structure TF, tagged with that TF."""
    bars: list[Bar] = []
    for tf, n in (("15m", 6), ("1h", 6), ("4h", 6), ("1d", 6)):
        # two quiet bars, a spike high, a lower confirmation, two more quiet
        bars.append(_bar(tf, 0, high="101", low="99", close="100"))
        bars.append(_bar(tf, 1, high="102", low="99", close="100"))
        bars.append(_bar(tf, 2, high="120", low="100", close="110"))  # swing high
        bars.append(_bar(tf, 3, high="111", low="100", close="105"))
        bars.append(_bar(tf, 4, high="106", low="99", close="100"))
        bars.append(_bar(tf, 5, high="101", low="99", close="100"))
    when = max(b.close_ts for b in bars) + timedelta(seconds=1)
    zones = ZoneEngine(tick_size=TICK).build("BTCUSDT", when, bars)
    swings = [z for z in zones if z.method == "swing" and z.side == "resistance"]
    tfs = {z.tf for z in swings}
    assert {"1h", "4h", "1d", "15m"} <= tfs
    for tf in ("1h", "4h", "1d", "15m"):
        hit = next(z for z in swings if z.tf == tf)
        assert hit.hi == Decimal("120")


def test_zone_width_uses_that_tf_atr_not_15m() -> None:
    """4h ATR is 8; 15m ATR is 0.4. A 4h swing must not inherit the 15m envelope."""
    h4 = _flat_series("4h", 16, mid="100", rng="8")
    # swing high on bar 17, confirmed by 18
    h4.append(_bar("4h", 16, high="120", low="100", close="110"))
    h4.append(_bar("4h", 17, high="111", low="100", close="105"))
    m15 = _flat_series("15m", 16, mid="100", rng="0.4")
    m15.append(_bar("15m", 16, high="120", low="100", close="110"))
    m15.append(_bar("15m", 17, high="111", low="100", close="105"))
    when = h4[-1].close_ts + timedelta(seconds=1)
    zones = ZoneEngine(tick_size=TICK).build("BTCUSDT", when, h4 + m15)
    z4 = next(z for z in zones if z.method == "swing" and z.tf == "4h" and z.side == "resistance")
    z15 = next(z for z in zones if z.method == "swing" and z.tf == "15m" and z.side == "resistance")
    atr4 = atr([b for b in h4 if b.close_ts < h4[-1].close_ts])
    atr15 = atr([b for b in m15 if b.close_ts < m15[-1].close_ts])
    assert atr4 is not None and atr15 is not None
    assert atr4 > atr15 * Decimal("5")
    width4 = z4.hi - z4.lo
    width15 = z15.hi - z15.lo
    assert width4 == max(TICK * 2, atr4 * ZONE_ATR_K)
    assert width15 == max(TICK * 2, atr15 * ZONE_ATR_K)
    assert width4 > width15


def test_unmeasured_atr_keeps_tick_epsilon() -> None:
    """Three bars cannot ATR. Width stays the tick floor — do not invent a move."""
    bars = [
        _bar("4h", 0, high="10", low="9", close="9.5"),
        _bar("4h", 1, high="20", low="10", close="19"),
        _bar("4h", 2, high="11", low="10", close="10.5"),
    ]
    when = bars[-1].close_ts + timedelta(seconds=1)
    zones = ZoneEngine(tick_size=TICK).build("BTCUSDT", when, bars)
    swing = next(z for z in zones if z.method == "swing" and z.tf == "4h")
    assert swing.hi - swing.lo == TICK * 2


def test_later_bars_do_not_resize_an_old_swing() -> None:
    """Width is PIT at created_as_of. A later ATR shift must not mint a new id."""
    early = _flat_series("4h", 16, mid="100", rng="8")
    early.append(_bar("4h", 16, high="120", low="100", close="110"))
    early.append(_bar("4h", 17, high="111", low="100", close="105"))
    later = list(early)
    for i in range(18, 30):
        later.append(_bar("4h", i, high="140", low="60", close="100"))
    t1 = early[-1].close_ts + timedelta(seconds=1)
    t2 = later[-1].close_ts + timedelta(seconds=1)
    engine = ZoneEngine(tick_size=TICK)
    a = next(z for z in engine.build("BTCUSDT", t1, early) if z.method == "swing" and z.tf == "4h")
    b = next(z for z in engine.build("BTCUSDT", t2, later) if z.method == "swing" and z.tf == "4h"
             and z.created_as_of == a.created_as_of)
    assert a.zone_id == b.zone_id
    assert a.lo == b.lo and a.hi == b.hi


def _level(tf: str, *, lo: str = "100", hi: str = "100.2") -> Zone:
    return Zone.create(
        symbol="BTCUSDT",
        tf=tf,
        side="support",
        lo=Decimal(lo),
        hi=Decimal(hi),
        method="swing",
        created_as_of=T0,
    )


def test_15m_through_does_not_kill_a_4h_level() -> None:
    zone = _level("4h")
    junior = _bar("15m", 20, high="100.3", low="99.0", close="99.0")
    t = junior.close_ts + timedelta(seconds=1)
    assert junior.close < zone.lo
    assert invalidated(zone, [junior], t=t) is False
    assert label(zone, junior, t=t, htf_bias="box") == "NOISE"


def test_4h_through_kills_the_4h_level() -> None:
    zone = _level("4h")
    own = _bar("4h", 3, high="100.3", low="99.0", close="99.0")
    t = own.close_ts + timedelta(seconds=1)
    assert invalidated(zone, [own], t=t) is True
    assert label(zone, own, t=t, htf_bias="box") == "THROUGH"


def test_engine_drops_a_level_its_own_tf_already_closed_through() -> None:
    bars = [
        _bar("4h", 0, high="101", low="99", close="100"),
        _bar("4h", 1, high="102", low="99", close="100"),
        _bar("4h", 2, high="120", low="100", close="110"),
        _bar("4h", 3, high="111", low="100", close="105"),
        _bar("4h", 4, high="130", low="90", close="91"),  # close through any support
    ]
    when = bars[-1].close_ts + timedelta(seconds=1)
    zones = ZoneEngine(tick_size=TICK).build("BTCUSDT", when, bars)
    supports = [z for z in zones if z.method == "swing" and z.side == "support" and z.tf == "4h"]
    assert all(not invalidated(z, bars, t=when) for z in supports)


def test_1h_reject_confirms_a_4h_level() -> None:
    zone = _level("4h")
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    t = hourly.close_ts + timedelta(seconds=1)
    assert confirm_label(zone, hourly, t=t, htf_bias="box") == "REJECT"
    assert pair_ready(zone, [hourly], t=t, htf_bias="box") is True


def test_4h_level_without_1h_confirm_is_not_ready() -> None:
    zone = _level("4h")
    m15 = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=datetime(2026, 8, 2, 12, 45, tzinfo=UTC),
        close_ts=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    t = m15.close_ts + timedelta(seconds=1)
    assert confirm_label(zone, m15, t=t, htf_bias="box") == "NOISE"
    assert pair_ready(zone, [m15], t=t, htf_bias="box") is False
    assert pair_ready(zone, [], t=t, htf_bias="box") is False


def test_15m_level_does_not_need_a_junior() -> None:
    zone = _level("15m")
    t = datetime(2026, 8, 2, 13, 0, 1, tzinfo=UTC)
    assert pair_ready(zone, [], t=t, htf_bias="box") is True


def test_1h_close_is_still_not_a_15m_cav_vote() -> None:
    """The 15m law stays: a foreign TF bar cannot vote a working-tf zone."""
    zone = _level("15m")
    hourly = Bar(
        symbol="BTCUSDT",
        tf="1h",
        open_ts=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal("100.1"),
    )
    t = hourly.close_ts + timedelta(seconds=1)
    assert label(zone, hourly, t=t, htf_bias="box") == "NOISE"
    assert confirm_label(zone, hourly, t=t, htf_bias="box") == "NOISE"


def test_desk_builder_closes_1h(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    desk = DeskLoop(knowledge=open_knowledge(vault), tick_size=TICK)
    st = desk.state_for("BTCUSDT")
    assert st.bar_builder is not None
    assert "1h" in st.bar_builder.tfs
    assert desk.config.structure_tfs == ("15m", "1h", "4h", "1d")
