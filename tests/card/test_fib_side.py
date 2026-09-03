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


def test_sweep_is_read_for_the_side_of_the_trade() -> None:
    """Audit §6: a swept swing HIGH is fuel for a short, not for a long."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from capitalizator.card.live import CardLive
    from capitalizator.card.sweep import sweep_status_for
    from capitalizator.zones.model import Bar

    t0 = datetime(2026, 9, 1, tzinfo=UTC)

    def bar(i: int, lo: str, hi: str, close: str) -> Bar:
        return Bar(
            symbol="BTCUSDT", tf="15m", open_ts=t0 + timedelta(minutes=15 * i),
            close_ts=t0 + timedelta(minutes=15 * (i + 1)),
            open=Decimal(close), high=Decimal(hi), low=Decimal(lo), close=Decimal(close),
            volume=Decimal("10"),
        )

    # swing high at bar 2 (105), swing low at bar 6 (95); tester sweeps the HIGH and closes back
    bars = [
        bar(0, "99", "102", "100"), bar(1, "100", "103", "101"), bar(2, "101", "105", "102"),
        bar(3, "100", "103", "101"), bar(4, "99", "101", "100"), bar(5, "97", "100", "98"),
        bar(6, "95", "99", "97"), bar(7, "96", "100", "99"), bar(8, "98", "101", "100"),
        bar(9, "99", "106", "103"),  # wick above 105, close 103 → high swept and back
    ]
    assert sweep_status_for(bars, "sell") == "done"
    assert sweep_status_for(bars, "buy") == "none"  # the low at 95 was never taken
    card = CardLive(
        symbol="BTCUSDT", bearing_verdict="propose", known_at=t0 + timedelta(hours=3),
        fib_zone="OTE", fib_zone_short="OTE", fvg_status="filled",
        sweep_status="done", sweep_long="none", sweep_short="done",
        pluses=("a", "b", "c", "d"), minuses=("e",),
    )
    assert card.sweep_for("sell") == "done" and card.sweep_for("buy") == "none"
    assert card.mark_green("sell")["sweep"] is True and card.mark_green("buy")["sweep"] is False
    assert card.context_ok("sell") is True and card.context_ok("buy") is False
    # an old card without side-aware labels falls back to the legacy reading
    legacy = CardLive.from_payload({**card.to_payload(), "sweep_long": None, "sweep_short": None})
    assert legacy.sweep_for("buy") == "done"
