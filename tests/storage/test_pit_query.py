"""0.2.8 — as_of=12:00Z does not see a fact known at 12:05Z."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.storage.pit import PitStore
from capitalizator.types import MarketEvent


def _trade(*, minute: int, second: int = 0) -> MarketEvent:
    ts = datetime(2026, 8, 30, 12, minute, second, tzinfo=UTC)
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": "1", "qty": "0.001", "side": "buy"},
    )


def test_slice_does_not_see_future() -> None:
    store = PitStore([_trade(minute=0), _trade(minute=5)])
    noon = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    rows = store.query("SELECT symbol, known_at FROM market_event", as_of=noon)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"


def test_later_slice_sees_both() -> None:
    store = PitStore([_trade(minute=0), _trade(minute=5)])
    later = datetime(2026, 8, 30, 12, 5, tzinfo=UTC)
    rows = store.query("SELECT * FROM market_event_pit ORDER BY known_at", as_of=later)
    assert len(rows) == 2


def test_naive_as_of_rejected() -> None:
    store = PitStore([_trade(minute=0)])
    with pytest.raises(TypeError, match="naive"):
        store.query("SELECT * FROM market_event", as_of=datetime(2026, 8, 30, 12, 0))


def test_sql_cannot_read_external_file(tmp_path: Path) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("px,qty\n1,2\n", encoding="utf-8")
    store = PitStore([_trade(minute=0)])
    as_of = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    with pytest.raises(Exception, match="external|Permission|IO|file|disabled"):
        store.query(f"SELECT * FROM read_csv_auto('{secret}')", as_of=as_of)
