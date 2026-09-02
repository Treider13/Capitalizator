"""D-20: a short at resistance reads the retrace from the low, not from the high."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from capitalizator.card.live import CardLive, fib_zone_at

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def test_long_and_short_readings_mirror() -> None:
    low, high = Decimal("100"), Decimal("110")
    # price at the high: a long is 0 retrace (forbidden); a short at the high is a
    # full pullback into resistance → 1.0 → in_05_1.
    assert fib_zone_at(low=low, high=high, price=Decimal("109.9"))[0] == "forbidden_0_05"
    assert fib_zone_at(low=low, high=high, price=Decimal("109.9"), side="sell")[0] == "in_05_1"
    # OTE band mirrors: 0.618–0.786 from either end
    assert fib_zone_at(low=low, high=high, price=Decimal("103"))[0] == "OTE"  # 0.7 from high
    assert fib_zone_at(low=low, high=high, price=Decimal("107"), side="sell")[0] == "OTE"
    assert fib_zone_at(low=low, high=high, price=Decimal("100.5"), side="sell")[0] == "forbidden_0_05"


def test_context_ok_uses_the_side_reading() -> None:
    card = CardLive(
        symbol="BTCUSDT",
        bearing_verdict="propose",
        known_at=NOW,
        fib_zone="forbidden_0_05",
        fib_zone_short="OTE",
        fvg_status="filled",
        sweep_status="done",
        pluses=("a", "b", "c", "d"),
        minuses=("e",),
    )
    assert card.context_ok() is False  # long reading forbidden
    assert card.context_ok(side="buy") is False
    assert card.context_ok(side="sell") is True
    assert card.mark_green(side="sell")["fib"] is True
    payload = card.to_payload()
    assert payload["fib_zone_short"] == "OTE"
    back = CardLive.from_payload(payload)
    assert back.fib_zone_short == "OTE" and back.context_ok(side="sell") is True


def test_old_payload_without_short_reading_defaults_to_none() -> None:
    card = CardLive(
        symbol="BTCUSDT", bearing_verdict="propose", known_at=NOW,
        pluses=("a", "b", "c", "d"), minuses=("e",),
    )
    raw = card.to_payload()
    del raw["fib_zone_short"]
    del raw["fib_level_short"]
    back = CardLive.from_payload(raw)
    assert back.fib_zone_short == "none"
    assert back.context_ok(side="sell") is False
