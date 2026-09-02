"""D-01/D-02: no side inversion. Spring trades with the zone; shadow R follows the side."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalizator.champion.shadow_day import idea_r, row_r, side_r, summarize
from capitalizator.exec.ideas import (
    CHALLENGER_IDEAS,
    SENDABLE_IDEAS,
    canonical,
    classify,
    opposite,
    shadow_tag,
    side_for,
)
from capitalizator.exec.strategy_bounce import stop_behind, stop_behind_wick
from capitalizator.patterns.cav import label as cav_label
from capitalizator.zones.model import Bar, Zone

T = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
SUP = Zone.create(
    symbol="BTCUSDT", tf="15m", side="support", lo=Decimal("100"), hi=Decimal("101"),
    method="prior_day_hl", created_as_of=T - timedelta(days=1),
)
RES = Zone.create(
    symbol="BTCUSDT", tf="15m", side="resistance", lo=Decimal("110"), hi=Decimal("111"),
    method="prior_day_hl", created_as_of=T - timedelta(days=1),
)


def _bar(low: str, high: str, close: str, open_: str = "100.5") -> Bar:
    return Bar(
        symbol="BTCUSDT", tf="15m", open_ts=T, close_ts=T + timedelta(minutes=15),
        open=Decimal(open_), high=Decimal(high), low=Decimal(low), close=Decimal(close),
        volume=Decimal("10"),
    )


def test_reject_bar_is_spring_and_trades_with_the_zone() -> None:
    bar = _bar(low="99.5", high="101.2", close="100.6")
    assert cav_label(SUP, bar, t=bar.close_ts + timedelta(microseconds=1), htf_bias="box") == "REJECT"
    assert classify(zone=SUP, bar=bar, cav_label="REJECT") == "spring"
    assert side_for("spring", "support") == "buy"
    assert side_for("spring", "resistance") == "sell"


def test_no_wick_through_is_bounce_with_zone() -> None:
    bar = _bar(low="100.2", high="101.2", close="100.6")
    assert classify(zone=SUP, bar=bar, cav_label="DRIFT") == "bounce"
    assert side_for("bounce", "support") == "buy"


def test_through_close_is_breakout_against_zone() -> None:
    bar = _bar(low="99", high="100.8", close="99.5")
    assert classify(zone=SUP, bar=bar, cav_label="THROUGH") == "breakout"
    assert side_for("breakout", "support") == "sell"
    assert side_for("breakout", "resistance") == "buy"


def test_legacy_failed_break_maps_to_spring_and_fade_is_challenger_only() -> None:
    assert canonical("failed_break") == "spring"
    assert side_for("failed_break", "support") == "buy"
    assert side_for("fade_spring", "support") == "sell"
    assert "fade_spring" in CHALLENGER_IDEAS and "fade_spring" not in SENDABLE_IDEAS
    with pytest.raises(ValueError):
        shadow_tag("fade_spring")
    assert opposite("buy") == "sell" and opposite("sell") == "buy"


def test_spring_stop_sits_behind_the_wick_not_inside_it() -> None:
    tick, away = Decimal("0.1"), 8
    band = stop_behind(SUP, tick, away, side="buy")
    assert band == Decimal("99.2")
    wick = stop_behind_wick(SUP, Decimal("98.5"), tick, away, side="buy")
    assert wick == Decimal("97.7") < band
    # a wick that never left the zone keeps the band stop (never a stop above the band)
    assert stop_behind_wick(SUP, Decimal("100.5"), tick, away, side="buy") == band
    # a wick just through the band still moves the stop below it
    assert stop_behind_wick(SUP, Decimal("99.9"), tick, away, side="buy") == Decimal("99.1")
    short = stop_behind_wick(RES, Decimal("112"), tick, away, side="sell")
    assert short == Decimal("112.8") > stop_behind(RES, tick, away, side="sell")


@pytest.mark.parametrize(
    ("side", "zone_side", "outcome", "r"),
    [
        ("buy", "support", "bounce", "1"),
        ("buy", "support", "break", "-1"),
        ("sell", "support", "bounce", "-1"),
        ("sell", "support", "break", "1"),
        ("sell", "resistance", "bounce", "1"),
        ("sell", "resistance", "break", "-1"),
        ("buy", "resistance", "bounce", "-1"),
        ("buy", "resistance", "break", "1"),
        ("buy", "support", "die", "0"),
    ],
)
def test_side_r_follows_the_side_taken(side: str, zone_side: str, outcome: str, r: str) -> None:
    assert side_r(side=side, zone_side=zone_side, outcome=outcome) == Decimal(r)


def test_side_r_pending_is_none_and_bad_side_is_error() -> None:
    assert side_r(side="buy", zone_side="support", outcome="pending") is None
    with pytest.raises(ValueError):
        side_r(side="long", zone_side="support", outcome="bounce")


def test_legacy_tag_rule_was_inverted_for_the_old_short() -> None:
    """The bug the audit found: tag said +1 while the sell lost."""
    legacy = idea_r("bounce", "bounce")  # failed_break_bounce → idea_of → bounce
    assert legacy == Decimal("1")
    real = side_r(side="sell", zone_side="support", outcome="bounce")
    assert real == Decimal("-1")


def test_row_r_prefers_sides_and_summarize_uses_it() -> None:
    day = "2026-09-01"
    ts = f"{day}T14:00:00+00:00"
    old_short = {
        "touch_ts": ts, "shadow_would": True, "shadow_tag": "failed_break_bounce",
        "shadow_side": "sell", "zone_side": "support", "outcome": "bounce",
    }
    spring_long = {
        "touch_ts": ts, "shadow_would": True, "shadow_tag": "spring",
        "shadow_side": "buy", "zone_side": "support", "outcome": "bounce",
    }
    legacy_row = {"touch_ts": ts, "shadow_would": True, "shadow_tag": "bounce", "outcome": "break"}
    assert row_r(old_short) == Decimal("-1")
    assert row_r(spring_long) == Decimal("1")
    assert row_r(legacy_row) == Decimal("-1")  # no sides → legacy rule
    snap = summarize([old_short, spring_long, legacy_row], day=day)
    assert snap.n_would == 3 and snap.n_resolved == 3
    assert snap.r_shadow == Decimal("-1")
