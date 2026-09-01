"""P0–P4 + P6: CardLive bus, calendar veto, ETH flatten, volume, trail.

B never sends. Telegram feeds are refused. Two observe() runs match.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.book.reconstruct import Book
from capitalizator.card.build import from_news
from capitalizator.card.live import CardLive, VolumeSnapshot, fib_zone_at, touch_line
from capitalizator.card.volume import snapshot as volume_snapshot
from capitalizator.exec.manage import TradeManager
from capitalizator.exec.strategy_bounce import BounceSnapshot, BounceStrategy
from capitalizator.jury.desk import decide, voices_for_bounce
from capitalizator.memory.registry import Registry
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.news_macro.rss import parse_rss, refuse_url
from capitalizator.ops.contour import ObserveIn, hours24, observe
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import RiskEngine
from capitalizator.types import MarketEvent
from capitalizator.zlg.gesture import BookAdd
from capitalizator.zones.model import Bar, Zone

TICK = Decimal("0.1")
CREATED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
ZONE = Zone.create(
    symbol="BTCUSDT",
    tf="1d",
    side="support",
    lo=Decimal("100"),
    hi=Decimal("100.2"),
    method="prior_day_hl",
    created_as_of=CREATED,
)
ETH_ZONE = Zone.create(
    symbol="ETHUSDT",
    tf="1d",
    side="support",
    lo=Decimal("3000"),
    hi=Decimal("3010"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _trade(
    ts: datetime,
    *,
    symbol: str = "BTCUSDT",
    px: str = "100.1",
    qty: str = "4",
    side: str = "sell",
) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": px, "qty": qty, "side": side},
    )


def _book(*, symbol: str = "BTCUSDT", bid: str = "100.1") -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol=symbol,
            exchange_ts=PRINT,
            seq=1,
            bids=((bid, "10"),),
            asks=(("100.3", "1"),),
        )
    )
    return book


def _bar(*, symbol: str = "BTCUSDT", close: str = "100.1") -> Bar:
    return Bar(
        symbol=symbol,
        tf="1d",
        open_ts=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        close_ts=datetime(2026, 8, 30, 16, 15, tzinfo=UTC),
        open=Decimal("100.1"),
        high=Decimal("100.5"),
        low=Decimal("99.9"),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def _reg(zone: Zone = ZONE, px: str = "100.1", symbol: str = "BTCUSDT") -> Registry:
    reg = Registry(tick_size=TICK)
    opened = reg.on_trade(_trade(PRINT, symbol=symbol, px=px), [zone])
    assert len(opened) == 1
    return reg


def _observe_in(*, card: CardLive | None = None, symbol: str = "BTCUSDT") -> ObserveIn:
    px = "100.1" if symbol == "BTCUSDT" else "3005"
    return ObserveIn(
        book=_book(symbol=symbol, bid=px),
        trades=[_trade(PRINT, symbol=symbol, px=px, qty="1", side="sell")],
        adds=[
            BookAdd(
                ts=PRINT + timedelta(seconds=1),
                side="bid",
                px=Decimal(px if symbol == "BTCUSDT" else "3005"),
                qty=Decimal("2"),
            )
        ],
        cav_bar=_bar(symbol=symbol, close=px),
        htf_bias="box",
        card=card,
    )


def _green(**kwargs: object) -> CardLive:
    base = dict(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="OTE",
        fib_level="0.718",
        rsi_htf="52",
        gex_bg="+2.1M",
        fvg_status="filled",
        sweep_status="done",
        pluses=("session_profile", "htf_ok", "rvol_above_2"),
        minuses=("base_rate_unknown", "spread_cost"),
        volume=VolumeSnapshot(rvol="2.3", poc="100", vah="101", val="99", walls="defend"),
    )
    base.update(kwargs)
    return CardLive(**base)  # type: ignore[arg-type]


def _news(
    *,
    event_id: str,
    klass: str,
    event_time: datetime,
    assets: tuple[str, ...] = ("BTCUSDT",),
    notes: str = "statement",
) -> NewsRow:
    return NewsRow(
        event_id=event_id,
        event_class=klass,
        event_time=event_time,
        known_at=NOW - timedelta(minutes=5),
        assets=assets,
        source="fed",
        announce_tz="UTC",
        size_rule="pre24_cut",
        notes=notes,
        raw=event_id,
    )


def test_p0_hours24_and_two_observe_runs_match() -> None:
    t0 = datetime(2026, 8, 29, 16, 30, tzinfo=UTC)
    end = t0 + timedelta(hours=24)
    gap = MarketEvent(
        stream="gap",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=t0,
        recv_ts=end,
        seq=None,
        payload={"ts_from": t0.isoformat(), "ts_to": end.isoformat()},
    )
    ok, span = hours24(
        [
            _trade(t0),
            _trade(end),
            gap,
        ]
    )
    assert ok is True
    assert span == 86400

    card = _green()

    def run() -> tuple[str | None, str | None, str | None]:
        reg = _reg()
        row = observe(reg, _observe_in(card=card), contour_on=True)[0]
        return row.jury, row.bearing_verdict, row.gesture

    assert run() == run()


def test_p0_observe_off_still_writes_nothing() -> None:
    reg = _reg()
    assert observe(reg, _observe_in(card=_green()), contour_on=False) == []
    assert reg.touches[0].jury is None


def test_p0_b_veto_skips_roles() -> None:
    card = _green(bearing_verdict="veto")
    reg = _reg()
    row = observe(reg, _observe_in(card=card), contour_on=True)[0]
    assert row.jury == "VETO"
    assert row.gesture is None
    assert row.cav_label is None
    assert row.bearing_verdict == "veto"


def test_p0_red_fib_is_split_even_without_zlg() -> None:
    card = _green(fib_zone="forbidden_0_05", fib_level="0.200")
    assert card.context_ok() is False
    reg = _reg()
    row = observe(reg, _observe_in(card=card), contour_on=True)[0]
    assert row.jury == "SPLIT"
    assert row.gesture is None
    assert row.skip_reason == "b_marks"


def test_p1_fomc_in_two_hours_is_veto() -> None:
    cal = (
        _news(
            event_id="fomc-surprise",
            klass="FOMC",
            event_time=NOW + timedelta(hours=2),
        ),
    )
    card = from_news(symbol="BTCUSDT", now=NOW, calendar=cal)
    assert card.bearing_verdict == "veto"
    assert any("fomc" in m for m in card.minuses)
    reg = _reg()
    row = observe(reg, _observe_in(card=card), contour_on=True)[0]
    assert row.jury == "VETO"
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    snap = BounceSnapshot(
        now=NOW,
        symbol="BTCUSDT",
        price=Decimal("100.1"),
        tick=TICK,
        trading_mode="demo",
        zone=ZONE,
        zones=(ZONE,),
        jury="ACCORD",
        cav_label="REJECT",
        zlg_label="DEFEND",
        n_cav=20,
        n_zlg=20,
        gesture_n=20,
        tape_eaten=False,
        btc_regime="box",
        card_bearing_verdict="propose",
        b_verdict="veto",
    )
    assert strat.propose(snap) is None
    mgr = TradeManager()
    got = mgr.on_refute(load_bearing=True, verdict="veto")
    assert got is not None and got.action == "flatten"


def test_p1_telegram_feed_refused() -> None:
    with pytest.raises(ValueError, match="telegram"):
        refuse_url("https://t.me/s/fed")
    with pytest.raises(ValueError, match="telegram"):
        parse_rss("<rss></rss>", source="https://t.me/channel", known_at=NOW)


def test_p1_official_rss_parses_fomc() -> None:
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>FOMC statement</title><link>https://www.federalreserve.gov/a</link></item>
    </channel></rss>"""
    rows = parse_rss(xml, source="https://www.federalreserve.gov/feed", known_at=NOW)
    assert rows[0].event_class == "FOMC"


def test_p2_eth_negative_flattens() -> None:
    cal = (
        _news(
            event_id="eth-hack",
            klass="HACK",
            event_time=NOW,
            assets=("ETHUSDT",),
            notes="hack exploit",
        ),
    )
    card = from_news(symbol="ETHUSDT", now=NOW, calendar=cal)
    assert card.bearing_verdict == "veto"
    assert "coin_negative" in card.minuses
    assert 5 <= len(card.pluses) + len(card.minuses) <= 7
    reg = _reg(ETH_ZONE, px="3005", symbol="ETHUSDT")
    row = observe(reg, _observe_in(card=card, symbol="ETHUSDT"), contour_on=True)[0]
    assert row.jury == "VETO"
    mgr = TradeManager()
    mgr.remaining = Decimal("1")
    assert mgr.on_refute(load_bearing=True, verdict="veto").action == "flatten"


def test_p3_volume_snapshot_fields() -> None:
    bars = [
        Bar(
            symbol="BTCUSDT",
            tf="15m",
            open_ts=PRINT + timedelta(minutes=i * 15),
            close_ts=PRINT + timedelta(minutes=i * 15 + 14),
            open=Decimal("100") + i,
            high=Decimal("101") + i,
            low=Decimal("99") + i,
            close=Decimal("100.5") + i,
            volume=Decimal(str(10 + i * 3)),
        )
        for i in range(8)
    ]
    snap = volume_snapshot(bars, walls="defend", eaten_levels="0")
    assert snap.poc
    assert snap.vah
    assert snap.val
    assert snap.vwap
    assert snap.delta
    assert snap.rvol
    assert snap.a_price
    assert snap.a_volume
    assert snap.a_delta
    assert snap.a_wall == "defend"
    zone, level = fib_zone_at(low=Decimal("90"), high=Decimal("110"), price=Decimal("95.64"))
    assert zone == "OTE"


def test_p4_knowledge_bus_and_touch_line(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "desk")
    kn = open_knowledge(vault)
    card = _green()
    kn.put_card_live("BTCUSDT", card.to_payload())
    raw = kn.get_card_live("BTCUSDT")
    kn.close()
    assert raw is not None
    loaded = CardLive.from_payload(raw)
    assert loaded.bearing_verdict == "propose"
    assert loaded.volume.rvol == "2.3"
    line = touch_line(symbol="BTCUSDT", card=loaded, jury="ACCORD")
    assert line.startswith("[TOUCH] BTCUSDT | B:propose | A:ACCORD")
    assert "Fib:0.718(OTE)" in line
    assert "RVOL:2.3" in line


def test_p6_positive_rvol_accord_and_trail() -> None:
    card = _green()
    assert Decimal(card.volume.rvol or "0") > 2
    assert card.context_ok()
    voices = voices_for_bounce(
        cav="REJECT",
        n_cav=20,
        zlg="DEFEND",
        n_zlg=20,
        tape_eaten=False,
        btc_regime="box",
        card_bearing_verdict=card.card_voice(),
    )
    assert decide(voices) == "ACCORD"
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    intent = strat.propose(
        BounceSnapshot(
            now=NOW,
            symbol="BTCUSDT",
            price=Decimal("100.1"),
            tick=TICK,
            trading_mode="demo",
            zone=ZONE,
            zones=(ZONE,),
            jury="ACCORD",
            cav_label="REJECT",
            zlg_label="DEFEND",
            n_cav=20,
            n_zlg=20,
            gesture_n=20,
            tape_eaten=False,
            btc_regime="box",
            card_bearing_verdict="propose",
            b_verdict="propose",
            b_marks_ok=True,
            rvol=Decimal("2.3"),
            macro_multiplier=Decimal("1"),
        )
    )
    assert intent is not None
    assert intent.qty is None
    mgr = TradeManager()
    one_r = intent.entry + (intent.entry - intent.stop)
    reduced = mgr.on_fill(side="buy", entry=intent.entry, stop=intent.stop, fill_px=one_r)
    assert reduced is not None
    assert reduced.action == "reduce"
    assert reduced.fraction == Decimal("0.5")
    trailed = mgr.trail_stop(Decimal("100.15"))
    assert trailed == Decimal("100.15")
    assert trailed != intent.entry


def test_p6_cut_size_applies_macro() -> None:
    strat = BounceStrategy(
        risk=RiskEngine(),
        halts=Halts(start_equity=Decimal("100000")),
        desk_mode="demo",
        require_card=False,
        require_jury=True,
    )
    intent = strat.propose(
        BounceSnapshot(
            now=NOW,
            symbol="BTCUSDT",
            price=Decimal("100.1"),
            tick=TICK,
            trading_mode="demo",
            zone=ZONE,
            zones=(ZONE,),
            jury="ACCORD",
            cav_label="REJECT",
            zlg_label="DEFEND",
            n_cav=20,
            n_zlg=20,
            gesture_n=20,
            tape_eaten=False,
            btc_regime="box",
            card_bearing_verdict="cut_size",
            b_verdict="cut_size",
            b_marks_ok=True,
            macro_multiplier=Decimal("0.5"),
        )
    )
    assert intent is not None
    assert intent.qty == Decimal("0.5")


def test_b_never_imports_signer() -> None:
    import capitalizator.card.build as build
    import capitalizator.card.live as live

    assert "signer" not in live.__dict__
    assert "signer" not in build.__dict__
    assert "propose" not in live.__dict__
