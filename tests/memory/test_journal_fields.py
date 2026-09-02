"""Journal width / quality / hour. Not a voice, not class_id, not a hash link."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.jury import desk
from capitalizator.memory.hashlog import touch_payload
from capitalizator.memory.registry import Registry, Touch
from capitalizator.patterns.bar_quality import QUALITY_LABELS
from capitalizator.types import MarketEvent
from capitalizator.zones.model import Bar, Zone

PATTERNS = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "patterns"

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _reg() -> Registry:
    reg = Registry(tick_size=TICK)
    trade = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=PRINT,
        recv_ts=PRINT,
        seq=None,
        payload={"px": "100.1", "qty": "0.001", "side": "buy"},
    )
    assert len(reg.on_trade(trade, [ZONE])) == 1
    return reg


def test_fill_width_and_quality_and_hour() -> None:
    reg = _reg()
    before = len(reg.chain.links)
    w = reg.fill_width(w_now=Decimal("1.5"), w_rank=Decimal("0.4"))
    q = reg.fill_bar_quality(quality="live")
    h = reg.fill_session_hour()
    assert w[0].w_now == Decimal("1.5")
    assert w[0].w_rank == Decimal("0.4")
    assert q[0].bar_quality == "live"
    assert h[0].session_hour == 16
    assert len(reg.chain.links) == before
    assert reg.chain.verify() is True


def test_voices_are_first_fact_journal_overwrites() -> None:
    """Merge contract: CAV stays; width/quality may restamp. One _patch, two laws."""
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    assert reg.fill_cav(cav_label="THROUGH") == []
    first = reg.fill_width(w_now=Decimal("2"), w_rank=Decimal("0.9"))[0]
    assert first.w_now == Decimal("2")
    assert first.cav_label == "REJECT"
    later = reg.fill_width(w_now=Decimal("3"), w_rank=Decimal("0.1"))[0]
    assert later.w_now == Decimal("3")
    assert later.w_rank == Decimal("0.1")
    assert later.cav_label == "REJECT"
    assert reg.fill_bar_quality(quality="live")[0].bar_quality == "live"
    q = reg.fill_bar_quality(quality="illiquid")[0]
    assert q.bar_quality == "illiquid"
    assert q.cav_label == "REJECT"


def test_journal_width_without_touch_id_writes_every_row() -> None:
    """Journal may paint every touch. Voices still need touch_id when several."""
    reg, first, second = _two_zone_reg()
    changed = reg.fill_width(w_now=Decimal("2"), w_rank=Decimal("0.5"))
    assert len(changed) == 2
    assert {t.touch_id for t in changed} == {first.touch_id, second.touch_id}
    assert all(t.w_now == Decimal("2") for t in reg.touches)
    later = reg.fill_width(w_now=Decimal("3"), w_rank=Decimal("0.1"))
    assert all(t.w_now == Decimal("3") for t in later)
    with pytest.raises(ValueError, match="touch_id"):
        reg.fill_cav(cav_label="REJECT")
    assert all(t.cav_label is None for t in reg.touches)


def test_sweep_and_fvg_marks_do_not_change_class_id() -> None:
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    row = reg.stamp_jury(n_cav=20, n_zlg=20)[0]
    assert row.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"
    later = reg.fill_sweep_wick(flag=True)[0]
    later = reg.fill_fvg_present(flag=True)[0]
    assert later.sweep_wick is True
    assert later.fvg_present is True
    assert later.jury == "ACCORD"
    assert later.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"


def test_journal_does_not_change_class_id() -> None:
    reg = _reg()
    reg.fill_cav(cav_label="REJECT")
    reg.fill_gesture(gesture="DEFEND")
    reg.fill_btc(regime="box")
    reg.fill_width(w_now=Decimal("2"), w_rank=Decimal("0.9"))
    reg.fill_bar_quality(quality="stagnant")
    reg.fill_session_hour()
    row = reg.stamp_jury(n_cav=20, n_zlg=20)[0]
    assert row.jury == "ACCORD"
    assert row.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"
    assert "16" not in row.rho_class_id
    assert "stagnant" not in row.rho_class_id
    assert "0.9" not in row.rho_class_id
    assert row.w_now == Decimal("2")
    assert row.w_rank == Decimal("0.9")
    assert row.bar_quality == "stagnant"
    assert row.session_hour == 16
    later = reg.fill_width(w_now=Decimal("3"), w_rank=Decimal("0.1"))[0]
    assert later.jury == "ACCORD"
    assert later.rho_class_id == "bounce × REJECT × DEFEND × BTC_box"
    assert later.w_now == Decimal("3")


def test_unknown_quality_rejected() -> None:
    reg = _reg()
    with pytest.raises(ValueError, match="bar_quality"):
        reg.fill_bar_quality(quality="gap")
    with pytest.raises(ValueError, match="bar_quality"):
        reg.fill_bar_quality(quality="LIVE")


def test_w_rank_requires_w_now() -> None:
    """A rank without a width cannot exist. Do not journal a hanging percentile."""
    reg = _reg()
    with pytest.raises(ValueError, match="w_rank requires w_now"):
        reg.fill_width(w_now=None, w_rank=Decimal("0.5"))
    cleared = reg.fill_width(w_now=None, w_rank=None)[0]
    assert cleared.w_now is None
    assert cleared.w_rank is None


def test_fill_quality_accepts_exactly_quality_labels() -> None:
    """Registry set must stay the same three labels classify_bar_quality returns."""
    assert QUALITY_LABELS == frozenset({"live", "stagnant", "illiquid"})
    reg = _reg()
    for quality in sorted(QUALITY_LABELS):
        assert reg.fill_bar_quality(quality=quality)[0].bar_quality == quality


def test_w_rank_outside_unit_rejected() -> None:
    reg = _reg()
    with pytest.raises(ValueError, match="w_rank"):
        reg.fill_width(w_now=Decimal("1"), w_rank=Decimal("1.1"))
    with pytest.raises(ValueError, match="w_now"):
        reg.fill_width(w_now=Decimal("-0.1"), w_rank=None)


def test_w_rank_unit_endpoints_are_kept() -> None:
    reg = _reg()
    lo = reg.fill_width(w_now=Decimal("0"), w_rank=Decimal("0"))[0]
    assert lo.w_now == Decimal("0")
    assert lo.w_rank == Decimal("0")
    hi = reg.fill_width(w_now=Decimal("0"), w_rank=Decimal("1"))[0]
    assert hi.w_rank == Decimal("1")


def test_two_runs_same_journal() -> None:
    def run() -> tuple[Decimal | None, str | None, int | None, str | None]:
        reg = _reg()
        reg.fill_width(w_now=Decimal("1.25"), w_rank=None)
        reg.fill_bar_quality(quality="illiquid")
        reg.fill_session_hour()
        row = reg.touches[0]
        return row.w_now, row.bar_quality, row.session_hour, row.rho_class_id

    assert run() == run()
    assert run() == (Decimal("1.25"), "illiquid", 16, None)


def _two_zone_reg() -> tuple[Registry, Touch, Touch]:
    other = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100.05"),
        hi=Decimal("100.25"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    reg = Registry(tick_size=TICK)
    trade = MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=PRINT,
        recv_ts=PRINT,
        seq=None,
        payload={"px": "100.1", "qty": "0.001", "side": "buy"},
    )
    opened = reg.on_trade(trade, [ZONE, other])
    assert len(opened) == 2
    return reg, opened[0], opened[1]


def test_fill_width_on_one_touch_does_not_write_the_other() -> None:
    reg, first, second = _two_zone_reg()
    reg.fill_width(w_now=Decimal("1.5"), w_rank=Decimal("0.2"), touch_id=first.touch_id)
    by_id = {t.touch_id: t for t in reg.touches}
    assert by_id[first.touch_id].w_now == Decimal("1.5")
    assert by_id[second.touch_id].w_now is None
    assert by_id[second.touch_id].w_rank is None


def test_fill_quality_and_hour_on_one_touch_do_not_write_the_other() -> None:
    reg, first, second = _two_zone_reg()
    reg.fill_bar_quality(quality="stagnant", touch_id=first.touch_id)
    reg.fill_session_hour(touch_id=first.touch_id)
    by_id = {t.touch_id: t for t in reg.touches}
    assert by_id[first.touch_id].bar_quality == "stagnant"
    assert by_id[first.touch_id].session_hour == 16
    assert by_id[second.touch_id].bar_quality is None
    assert by_id[second.touch_id].session_hour is None


def test_resolve_keeps_journal_fields() -> None:
    """Outcome replace must not drop width / quality / hour."""
    def _journal(reg: Registry) -> None:
        reg.fill_width(w_now=Decimal("1.5"), w_rank=Decimal("0.4"))
        reg.fill_bar_quality(quality="live")
        reg.fill_session_hour()

    def _assert_journal(row: Touch) -> None:
        assert row.w_now == Decimal("1.5")
        assert row.w_rank == Decimal("0.4")
        assert row.bar_quality == "live"
        assert row.session_hour == 16

    bounce = _reg()
    _journal(bounce)
    later = PRINT + timedelta(minutes=20)
    bounced = bounce.resolve(now=later, bars=[], last_px=Decimal("101.0"))
    assert [t.outcome for t in bounced] == ["bounce"]
    _assert_journal(bounced[0])

    brk = _reg()
    _journal(brk)
    close_ts = PRINT + timedelta(minutes=15)
    bar = Bar(
        symbol="BTCUSDT",
        tf="15m",
        open_ts=close_ts - timedelta(minutes=15),
        close_ts=close_ts,
        open=Decimal("99.9"),
        high=Decimal("99.9"),
        low=Decimal("99.9"),
        close=Decimal("99.9"),
    )
    broken = brk.resolve(now=close_ts + timedelta(seconds=1), bars=[bar], last_px=Decimal("101.0"))
    assert [t.outcome for t in broken] == ["break"]
    _assert_journal(broken[0])

    dying = _reg()
    _journal(dying)
    died = dying.resolve(now=PRINT + timedelta(hours=6, seconds=1), bars=[], last_px=Decimal("100.1"))
    assert [t.outcome for t in died] == ["die"]
    _assert_journal(died[0])


def test_stamp_jury_on_one_touch_keeps_the_other_and_journal() -> None:
    reg, first, second = _two_zone_reg()
    reg.fill_width(w_now=Decimal("2"), w_rank=Decimal("0.5"))
    for tid in (first.touch_id, second.touch_id):
        reg.fill_cav(cav_label="REJECT", touch_id=tid)
        reg.fill_gesture(gesture="DEFEND", touch_id=tid)
        reg.fill_btc(regime="box", touch_id=tid)
    reg.stamp_jury(n_cav=20, n_zlg=20, touch_id=first.touch_id)
    by_id = {t.touch_id: t for t in reg.touches}
    assert by_id[first.touch_id].jury == "ACCORD"
    assert by_id[first.touch_id].rho_class_id == "bounce × REJECT × DEFEND × BTC_box"
    assert by_id[first.touch_id].w_now == Decimal("2")
    assert by_id[second.touch_id].jury is None
    assert by_id[second.touch_id].rho_class_id is None
    assert by_id[second.touch_id].w_now == Decimal("2")


def test_patterns_modules_do_not_import_memory() -> None:
    """WidthSample exists so patterns never see Touch."""
    for name in ("width.py", "bar_quality.py", "exam.py", "cav.py"):
        text = (PATTERNS / name).read_text(encoding="utf-8")
        assert "capitalizator.memory" not in text
        assert "from capitalizator.memory" not in text


def test_naive_touch_ts_rejected() -> None:
    """Touch.ts follows Bar: naive is forbidden at construction, not only at fill."""
    with pytest.raises(TypeError, match="naive"):
        Touch(
            touch_id="naive",
            zone_id=ZONE.zone_id,
            ts=datetime(2026, 8, 30, 16, 30),
            trade_px=Decimal("100.1"),
            trade_qty=Decimal("0.001"),
            outcome="pending",
        )


def test_offset_timezone_session_hour_is_utc_not_local() -> None:
    """+3 16:30 is 13:30Z. ts.hour would be 16 — that is not the journal field."""
    plus3 = timezone(timedelta(hours=3))
    ts = datetime(2026, 8, 30, 16, 30, tzinfo=plus3)
    assert ts.hour == 16
    reg = Registry(tick_size=TICK)
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=CREATED,
    )
    reg.on_trade(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=ts,
            recv_ts=ts,
            seq=None,
            payload={"px": "100.1", "qty": "0.001", "side": "buy"},
        ),
        [zone],
    )
    assert reg.fill_session_hour()[0].session_hour == 13
    direct = Registry(tick_size=TICK)
    direct.touches = [
        Touch(
            touch_id="off",
            zone_id=ZONE.zone_id,
            ts=ts,
            trade_px=Decimal("100.1"),
            trade_qty=Decimal("0.001"),
            outcome="pending",
        )
    ]
    assert direct.fill_session_hour()[0].session_hour == 13


def test_plus9_session_hour_is_not_hardcoded_plus3() -> None:
    """+9 16:30 is 07:30Z. `(hour - 3) % 24` would still write 13."""
    plus9 = timezone(timedelta(hours=9))
    ts = datetime(2026, 8, 30, 16, 30, tzinfo=plus9)
    assert ts.hour == 16
    direct = Registry(tick_size=TICK)
    direct.touches = [
        Touch(
            touch_id="plus9",
            zone_id=ZONE.zone_id,
            ts=ts,
            trade_px=Decimal("100.1"),
            trade_qty=Decimal("0.001"),
            outcome="pending",
        )
    ]
    assert direct.fill_session_hour()[0].session_hour == 7


def test_two_touches_keep_their_own_utc_hours() -> None:
    born = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    first_zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=born,
    )
    other = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100.05"),
        hi=Decimal("100.25"),
        method="prior_day_hl",
        created_as_of=born,
    )
    reg = Registry(tick_size=TICK)
    night = datetime(2026, 8, 30, 0, 15, tzinfo=UTC)
    day = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    for ts, zones in ((night, [first_zone]), (day, [other])):
        reg.on_trade(
            MarketEvent(
                stream="trades",
                exchange="bybit",
                symbol="BTCUSDT",
                exchange_ts=ts,
                recv_ts=ts,
                seq=None,
                payload={"px": "100.1", "qty": "0.001", "side": "buy"},
            ),
            zones,
        )
    assert len(reg.touches) == 2
    hours = sorted(t.session_hour for t in reg.fill_session_hour())
    assert hours == [0, 16]


def test_midnight_utc_session_hour_is_zero() -> None:
    midnight = datetime(2026, 8, 30, 0, 15, tzinfo=UTC)
    zone = Zone.create(
        symbol="BTCUSDT",
        tf="1d",
        side="support",
        lo=Decimal("100"),
        hi=Decimal("100.2"),
        method="prior_day_hl",
        created_as_of=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )
    reg = Registry(tick_size=TICK)
    reg.on_trade(
        MarketEvent(
            stream="trades",
            exchange="bybit",
            symbol="BTCUSDT",
            exchange_ts=midnight,
            recv_ts=midnight,
            seq=None,
            payload={"px": "100.1", "qty": "0.001", "side": "buy"},
        ),
        [zone],
    )
    assert reg.fill_session_hour()[0].session_hour == 0


def test_journal_is_invisible_to_jury_and_hash() -> None:
    assert list(desk.Voices.__dataclass_fields__) == ["cav", "zlg", "tape", "btc", "card"]
    src = inspect.getsource(desk)
    assert "w_now" not in src
    assert "w_rank" not in src
    assert "bar_quality" not in src
    assert "session_hour" not in src
    assert "hostile_exam" not in src
    assert "fvg_present" not in src
    assert "sweep_wick" not in src
    assert "no_tvh" not in src
    payload_src = inspect.getsource(touch_payload)
    assert "w_now" not in payload_src
    assert "session_hour" not in payload_src
    assert inspect.signature(desk.rho_class_id).parameters.keys() == {
        "setup",
        "cav",
        "zlg",
        "btc",
    }
