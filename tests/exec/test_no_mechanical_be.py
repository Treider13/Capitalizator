"""No move_to_be_at_pct=0.02. +2% price with a wide stop is not a flatten and not a half."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.exec.paper import PaperEngine
from capitalizator.exec.trail import TrailEngine
from capitalizator.types import MarketEvent

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "exec"
T0 = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def test_no_mechanical_be_knob_anywhere_in_exec() -> None:
    for name in ("manage.py", "trail.py", "paper.py", "smart_stop.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        assert "move_to_be_at_pct" not in text
    assert not hasattr(TrailEngine, "move_to_be_at_pct")


def test_two_percent_price_is_not_be() -> None:
    """Stop 4% away. +2% is 0.5R — no half, no stop move to entry."""
    eng = PaperEngine()
    pos = eng.submit(
        paper_id="p", touch_id="t", symbol="BTCUSDT", side="buy", limit_px=Decimal("100"),
        qty=Decimal("1"), stop=Decimal("96"), tp=Decimal("112"), tick=Decimal("0.1"), now=T0,
        valid_for=timedelta(minutes=30), source="shadow", tag="bounce",
    )
    mk = lambda px, side: MarketEvent(  # noqa: E731
        stream="trades", exchange="bybit", symbol="BTCUSDT",
        exchange_ts=T0 + timedelta(seconds=1), recv_ts=T0 + timedelta(seconds=1),
        payload={"px": px, "qty": "1", "side": side},
    )
    eng.on_print(mk("99.9", "sell"))
    eng.on_print(mk("102", "buy"))
    assert pos.state == "open" and not pos.half_taken
    assert pos.stop == Decimal("96")  # nothing moved the stop to entry
