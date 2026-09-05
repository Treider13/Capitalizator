"""After the 1R take, a score drop flattens the remainder. It never adds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from capitalizator.exec.paper import PaperEngine
from capitalizator.types import MarketEvent

T0 = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def _print(ts: datetime, px: str, side: str = "buy") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "0.1", "side": side},
    )


def test_score_drop_flattens_remainder_only() -> None:
    eng = PaperEngine()
    pos = eng.submit(
        paper_id="t1:shadow",
        touch_id="t1",
        symbol="BTCUSDT",
        side="buy",
        limit_px=Decimal("100"),
        qty=Decimal("1"),
        stop=Decimal("98"),
        tp=Decimal("104"),
        tick=Decimal("0.1"),
        now=T0,
        valid_for=timedelta(minutes=30),
        source="shadow",
        tag="bounce",
    )
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9", side="sell"))
    eng.on_print(_print(T0 + timedelta(minutes=1), "102", side="buy"))
    assert pos.half_taken and pos.qty_open == Decimal("0.5")
    closed = eng.note_score(
        pos.paper_id,
        now=T0 + timedelta(minutes=2),
        px=Decimal("101"),
        score_now=Decimal("0.40"),
        score_entry=Decimal("0.70"),
        drop=Decimal("0.20"),
    )
    assert closed is True
    assert pos.state == "closed"
    assert pos.exit_reason == "score"
    assert pos.qty_open == Decimal("0")


def test_score_hold_leaves_remainder() -> None:
    eng = PaperEngine()
    pos = eng.submit(
        paper_id="t1:shadow",
        touch_id="t1",
        symbol="BTCUSDT",
        side="buy",
        limit_px=Decimal("100"),
        qty=Decimal("1"),
        stop=Decimal("98"),
        tp=Decimal("104"),
        tick=Decimal("0.1"),
        now=T0,
        valid_for=timedelta(minutes=30),
        source="shadow",
        tag="bounce",
    )
    eng.on_print(_print(T0 + timedelta(seconds=1), "99.9", side="sell"))
    eng.on_print(_print(T0 + timedelta(minutes=1), "102", side="buy"))
    assert (
        eng.note_score(
            pos.paper_id,
            now=T0 + timedelta(minutes=2),
            px=Decimal("103"),
            score_now=Decimal("0.65"),
            score_entry=Decimal("0.70"),
            drop=Decimal("0.20"),
        )
        is False
    )
    assert pos.state == "open" and pos.qty_open == Decimal("0.5")
