"""PRS τ from PASSIVE-RESILIENCE.md. Same fixture → same Y. No place_order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.book.reconstruct import Book
from capitalizator.prs.score import PRS
from capitalizator.recorder.rest_snapshot import BookSnapshot
from capitalizator.types import MarketEvent

T0 = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
PRS_DIR = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "prs"


def _book(bid_sz: str, *, u: int = 1) -> Book:
    book = Book(tick_size="0.1")
    book.apply_snapshot(
        BookSnapshot(
            symbol="BTCUSDT",
            exchange_ts=T0,
            seq=u,
            bids=(("100", bid_sz),),
            asks=(("100.2", "1"),),
        )
    )
    return book


def _hit(qty: str = "2") -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=T0,
        recv_ts=T0,
        seq=None,
        payload={"px": "100", "qty": qty, "side": "sell"},
    )


def test_known_tau_three_seconds() -> None:
    """D_pre=10, α=0.7 → target 7. First ready book at +3s has 7."""
    prs = PRS(tick_size=Decimal("0.1"))
    got = prs.compute(_hit(), _book("10"), [(T0 + timedelta(seconds=3), _book("7", u=2))])
    assert got.tau == Decimal("3")
    assert got.censored is False
    assert got.d_pre == Decimal("10")
    # X = ln(1 + 3 / (1 + 2/10)) = ln(3.5)
    assert got.X == (Decimal("1") + Decimal("3") / Decimal("1.2")).ln()
    assert got.Y is None


def test_no_recovery_is_censored_tmax() -> None:
    prs = PRS(tick_size=Decimal("0.1"))
    got = prs.compute(_hit(), _book("10"), [(T0 + timedelta(seconds=3), _book("2", u=2))])
    assert got.tau == Decimal("8")
    assert got.censored is True


def test_same_fixture_twice_same_y() -> None:
    path = [(T0 + timedelta(seconds=3), _book("7", u=2))]

    def run() -> Decimal:
        prs = PRS(tick_size=Decimal("0.1"))
        last = None
        for i in range(30):
            last = prs.compute(_hit(), _book("10"), path)
            assert last is not None
        assert last is not None
        assert last.Y is not None
        return last.Y

    assert run() == run()


def test_prs_source_has_no_place_order() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in PRS_DIR.glob("*.py"))
    assert "place_order" not in text
    assert "create_order" not in text
