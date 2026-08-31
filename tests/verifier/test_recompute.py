"""2.11.2 — same SQL, swapped number → REFUTED. No store → UNVERIFIABLE."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.card.draft import CardDraft, apply_bind
from capitalizator.storage.pit import PitStore
from capitalizator.types import MarketEvent
from capitalizator.verifier.sql_pit import SqlVerifier

SQL = (
    "SELECT COUNT(*) FILTER (WHERE symbol = 'BTCUSDT'), "
    "COUNT(*) FROM market_event"
)
AS_OF = datetime(2026, 8, 30, 12, 30, tzinfo=UTC)


def _trade(symbol: str, minute: int) -> MarketEvent:
    ts = datetime(2026, 8, 30, 12, minute, tzinfo=UTC)
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol=symbol,
        exchange_ts=ts,
        recv_ts=ts,
        seq=None,
        payload={"px": "1", "qty": "0.001", "side": "buy"},
    )


def _store() -> PitStore:
    btc = [_trade("BTCUSDT", i) for i in range(23)]
    eth = [_trade("ETHUSDT", i) for i in range(23, 31)]
    return PitStore(btc + eth)


def test_matching_two_integers_is_verified() -> None:
    got = SqlVerifier().recompute("23 из 31", SQL, _store(), as_of=AS_OF)
    assert got.verdict == "VERIFIED"
    assert got.claim == "23 из 31"


def test_tampered_number_same_sql_is_refuted() -> None:
    got = SqlVerifier().recompute("24 из 31", SQL, _store(), as_of=AS_OF)
    assert got.verdict == "REFUTED"


def test_no_store_is_unverifiable() -> None:
    got = SqlVerifier().recompute("23 из 31", SQL, None, as_of=AS_OF)
    assert got.verdict == "UNVERIFIABLE"


def test_future_slice_does_not_invent_the_count() -> None:
    early = datetime(2026, 8, 30, 12, 10, tzinfo=UTC)
    got = SqlVerifier().recompute("23 из 31", SQL, _store(), as_of=early)
    assert got.verdict == "REFUTED"


def test_free_text_claim_is_unverifiable() -> None:
    got = SqlVerifier().recompute("зона красивая", SQL, _store(), as_of=AS_OF)
    assert got.verdict == "UNVERIFIABLE"


def test_verified_without_result_file_cannot_stamp() -> None:
    stamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    claims = [
        {
            "type": "unit",
            "subject": "BTCUSDT",
            "value": "23 из 31" if i == 0 else f"fixture-{i}",
            "as_of": stamp,
            "known_at": stamp,
            "horizon": "1h",
            "load_bearing": i == 0,
        }
        for i in range(5)
    ]
    card = CardDraft.model_validate({"thesis": "unit fixture", "claims": claims})
    receipt = SqlVerifier().recompute("23 из 31", SQL, _store(), as_of=AS_OF)
    assert receipt.verdict == "VERIFIED"
    with pytest.raises(ValueError, match="query file"):
        apply_bind(card, 0, receipt)
