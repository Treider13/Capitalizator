"""W3 paper engine: deterministic on the tape, costs included, no tag-based ±1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.exec.fees import FeeTable
from capitalizator.exec.paper import PaperEngine
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def _print(ts: datetime, px: str, side: str = "sell", symbol: str = "BTCUSDT") -> MarketEvent:
    return MarketEvent(
        stream="trades", exchange="bybit", symbol=symbol, exchange_ts=ts, recv_ts=ts,
        payload={"px": px, "qty": "0.1", "side": side},
    )


def _engine(**kw) -> PaperEngine:
    return PaperEngine(**kw)


def _buy(engine: PaperEngine, **over):
    args = dict(
        paper_id="t1:shadow", touch_id="t1", symbol="BTCUSDT", side="buy",
        limit_px=Decimal("100"), qty=Decimal("1"), stop=Decimal("98"), tp=Decimal("104"),
        tick=Decimal("0.1"), now=T0, valid_for=timedelta(minutes=30), source="shadow",
        tag="bounce",
    )
    args.update(over)
    return engine.submit(**args)


def test_conservative_fill_needs_trade_through_or_seller_at_limit() -> None:
    eng = _engine()
    pos = _buy(eng)
    eng.on_print(_print(T0 + timedelta(seconds=1), "100", side="buy"))  # buyer lifted at 100: not us
    assert pos.state == "pending" and pos.naive_fill_at is not None
    eng.on_print(_print(T0 + timedelta(seconds=2), "100", side="sell"))  # seller hit our bid
    assert pos.state == "open" and pos.entry_px == Decimal("100")
    assert pos.fees == Decimal("1") * Decimal("100") * FeeTable.VIP0_MAKER


def test_stop_is_market_with_slippage_and_taker_fee() -> None:
    eng = _engine(slippage_ticks=2)
    pos = _buy(eng)
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9"))
    assert pos.state == "open"
    eng.on_print(_print(T0 + timedelta(seconds=5), "97.9"))
    assert pos.state == "closed" and pos.exit_reason == "stop"
    assert pos.exit_px == Decimal("98") - Decimal("0.2")
    assert pos.realized == (Decimal("97.8") - Decimal("100")) * 1
    expected_fees = Decimal("100") * FeeTable.VIP0_MAKER + Decimal("97.8") * FeeTable.VIP0_TAKER
    assert pos.fees == expected_fees
    assert pos.r_gross() == Decimal("-2.2") / Decimal("2")
    assert pos.r_net() < pos.r_gross()
    assert pos.mae_r() == Decimal("2.1") / Decimal("2")  # worst print 97.9 → 2.1 against


def test_half_at_one_r_then_tp_on_remainder() -> None:
    eng = _engine()
    pos = _buy(eng)
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9"))
    eng.on_print(_print(T0 + timedelta(minutes=1), "102"))  # +1R → half at 102
    assert pos.half_taken and pos.half_px == Decimal("102") and pos.qty_open == Decimal("0.5")
    assert pos.realized == Decimal("2") * Decimal("0.5")
    eng.on_print(_print(T0 + timedelta(minutes=2), "104.5"))  # tp 104 on the rest
    assert pos.state == "closed" and pos.exit_reason == "tp" and pos.exit_px == Decimal("104")
    assert pos.realized == Decimal("1") + Decimal("4") * Decimal("0.5")
    assert pos.r_gross() == Decimal("3") / Decimal("2")
    assert pos.mfe_r() == Decimal("4.5") / Decimal("2")
    assert pos.r_net() < pos.r_gross()  # fees on entry, half and tp
    payload = pos.to_payload()
    assert payload["hold_s"] == 119.0 and payload["exit_reason"] == "tp"


def test_pending_expires_by_clock_and_by_print() -> None:
    eng = _engine()
    pos = _buy(eng)
    eng.on_clock(T0 + timedelta(minutes=29))
    assert pos.state == "pending"
    eng.on_clock(T0 + timedelta(minutes=31))
    assert pos.state == "closed" and pos.exit_reason == "expired" and pos.entry_px is None
    assert pos.r_net() is None  # unfilled is not scored
    pos2 = _buy(eng, paper_id="t2:shadow", touch_id="t2")
    eng.on_print(_print(T0 + timedelta(minutes=40), "150"))
    assert pos2.exit_reason == "expired"


def test_time_stop_and_funding_charged_per_settlement() -> None:
    eng = _engine(funding_rate=lambda s: Decimal("0.0001"), max_hold=timedelta(hours=6))
    # settle boundaries every 480 min from epoch; T0 14:00Z sits inside slot; next at 16:00Z
    pos = _buy(eng, stop=Decimal("90"), tp=Decimal("120"))
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9"))
    eng.on_print(_print(T0 + timedelta(hours=3), "100.5"))  # crosses 16:00Z settlement
    assert pos.funding == Decimal("0.0001") * Decimal("100") * 1  # long pays
    eng.on_print(_print(T0 + timedelta(hours=6, seconds=1), "100.4"))
    assert pos.state == "closed" and pos.exit_reason == "time"
    assert pos.funding > 0 and pos.pnl_net() == pos.realized - pos.fees - pos.funding


def test_short_side_mirrors_and_receives_funding() -> None:
    eng = _engine(funding_rate=lambda s: Decimal("0.0001"))
    pos = eng.submit(
        paper_id="s:fade", touch_id="s", symbol="BTCUSDT", side="sell",
        limit_px=Decimal("100"), qty=Decimal("1"), stop=Decimal("102"), tp=Decimal("96"),
        tick=Decimal("0.1"), now=T0, valid_for=timedelta(minutes=30), source="fade",
        tag="fade_spring",
    )
    eng.on_print(_print(T0 + timedelta(seconds=1), "100", side="buy"))  # buyer lifted our ask
    assert pos.state == "open"
    eng.on_print(_print(T0 + timedelta(hours=3), "99"))
    assert pos.funding < 0  # short receives
    eng.on_print(_print(T0 + timedelta(hours=3, minutes=1), "102.1"))
    assert pos.exit_reason == "stop" and pos.exit_px == Decimal("102.1")


def test_set_stop_is_monotone_and_only_when_open() -> None:
    eng = _engine()
    pos = _buy(eng)
    assert eng.set_stop("t1:shadow", Decimal("99"), reason="trail") is False  # pending
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9"))
    assert eng.set_stop("t1:shadow", Decimal("97"), reason="trail") is False  # would loosen
    assert eng.set_stop("t1:shadow", Decimal("99"), reason="trail") is True
    assert pos.stop == Decimal("99") and pos.stop_moves == [("98", "99")]
    assert eng.set_stop("nope", Decimal("99"), reason="trail") is False


def test_flatten_closes_pending_and_open() -> None:
    eng = _engine()
    a = _buy(eng)
    b = _buy(eng, paper_id="t2:shadow", touch_id="t2", limit_px=Decimal("95"), stop=Decimal("93"))
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9"))
    out = eng.flatten("BTCUSDT", Decimal("100.2"), T0 + timedelta(minutes=5))
    assert {p.paper_id for p in out} == {"t1:shadow", "t2:shadow"}
    assert a.exit_reason == "flatten" and a.exit_px == Decimal("100.2")
    assert b.exit_reason == "flatten" and b.entry_px is None


def test_bad_geometry_and_duplicate_rejected() -> None:
    eng = _engine()
    with pytest.raises(ValueError, match="buy stop"):
        _buy(eng, stop=Decimal("101"))
    _buy(eng)
    with pytest.raises(ValueError, match="duplicate"):
        _buy(eng)


def test_stats_count_filled_only_and_report_costs() -> None:
    closed: list = []
    eng = _engine(on_close=closed.append)
    win = _buy(eng)
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9"))
    eng.on_print(_print(T0 + timedelta(minutes=1), "104.1"))
    loss = _buy(eng, paper_id="t2:shadow", touch_id="t2")
    eng.on_print(_print(T0 + timedelta(minutes=2), "99.9"))
    eng.on_print(_print(T0 + timedelta(minutes=3), "97.9"))
    _buy(eng, paper_id="t3:shadow", touch_id="t3")
    eng.on_clock(T0 + timedelta(hours=1))  # expired, unfilled
    stats = eng.stats()
    assert stats["n"] == 2 and stats["n_unfilled"] == 1
    assert stats["winrate"] == Decimal("0.5")
    assert stats["profit_factor"] is not None and stats["profit_factor"] > 1
    assert stats["fees"] == win.fees + loss.fees
    assert len(closed) == 3
