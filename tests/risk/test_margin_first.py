"""Э1 — two operator knobs, margin-first. The deposit share IS the size.

Before: qty = min(target_risk, deposit_share, 10% cap). A 4%+ stop silently
shrank the position to keep 1% risk; 20–30% share was capped at 10%.
After: the operator's share is the margin that goes in; implied risk is a
warning; a stop wider than max_stop_pct is refused, not fitted; a stop past
the isolated-liq estimate is refused (the venue would liquidate first).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.ops.ops_page import RISK_HINTS, render_ops_html
from capitalizator.risk.config import RiskConfig, parse_deposit_share, parse_max_stop_pct
from capitalizator.risk.halts import Halts
from capitalizator.risk.sizing import isolated_liq_price, size_position

COMMON = dict(
    equity=Decimal("100000"),
    entry=Decimal("65000"),
    lev=Decimal("3"),
    target_risk=Decimal("0.01"),
    qty_step=Decimal("0.001"),
    min_qty=Decimal("0.001"),
    min_notional=Decimal("5"),
)


def test_deposit_share_is_the_size_even_when_risk_exceeds_target() -> None:
    """4.6% stop: old sizer bound on target_risk (0.333 BTC). Share 10% × 3x = 0.461."""
    got = size_position(stop=Decimal("62000"), deposit_share=Decimal("0.10"), **COMMON)
    assert got.action == "accept"
    assert got.binding == "deposit_share"
    assert got.qty == Decimal("0.461")
    assert got.margin == Decimal("0.461") * Decimal("65000") / Decimal("3")
    assert got.risk_frac > Decimal("0.01")
    assert got.risk_warning is True
    assert got.warning == "risk_above_target"


def test_twenty_and_thirty_percent_are_not_capped_at_ten() -> None:
    ten = size_position(stop=Decimal("64300"), deposit_share=Decimal("0.10"), **COMMON)
    twenty = size_position(stop=Decimal("64300"), deposit_share=Decimal("0.20"), **COMMON)
    thirty = size_position(stop=Decimal("64300"), deposit_share=Decimal("0.30"), **COMMON)
    assert ten.qty == Decimal("0.461")
    assert twenty.qty == Decimal("0.923")
    assert thirty.qty == Decimal("1.384")
    # the leftover 10% hard cap must not shrink 20/30
    assert twenty.margin > Decimal("10000")
    assert thirty.margin > Decimal("20000")
    assert {ten.binding, twenty.binding, thirty.binding} == {"deposit_share"}


def test_tight_stop_does_not_inflate_past_the_share() -> None:
    """0.1% stop used to let the risk budget ask for 15 BTC; the share still binds."""
    got = size_position(stop=Decimal("64935"), deposit_share=Decimal("0.10"), **COMMON)
    assert got.action == "accept" and got.binding == "deposit_share"
    assert got.qty == Decimal("0.461")
    assert got.risk_warning is False


def test_max_stop_pct_refuses_a_stop_the_operator_did_not_allow() -> None:
    # 6.15% stop, ceiling 5%
    got = size_position(
        stop=Decimal("61000"),
        deposit_share=Decimal("0.10"),
        max_stop_pct=Decimal("0.05"),
        **COMMON,
    )
    assert got.action == "reject" and got.binding == "max_stop_pct"
    assert got.qty == 0


def test_five_percent_stop_is_allowed_when_the_operator_set_five() -> None:
    stop = Decimal("65000") * Decimal("0.95")  # exactly 5%
    got = size_position(
        stop=stop, deposit_share=Decimal("0.10"), max_stop_pct=Decimal("0.05"), **COMMON
    )
    assert got.action == "accept"
    assert got.risk_frac == got.qty * (Decimal("65000") - stop) / Decimal("100000")


def test_stop_past_isolated_liq_is_refused() -> None:
    # 3x isolated long liq ≈ 67% of entry; a stop at 60% is past it.
    liq = isolated_liq_price(entry=Decimal("65000"), lev=Decimal("3"), side="buy")
    assert liq < Decimal("65000") * Decimal("0.70")
    got = size_position(
        stop=liq - Decimal("100"),
        deposit_share=Decimal("0.10"),
        side="buy",
        **COMMON,
    )
    assert got.action == "reject" and got.binding == "stop_past_liq"
    # a 2% stop is well inside the 3x liq
    ok = size_position(
        stop=Decimal("63700"), deposit_share=Decimal("0.10"), side="buy", **COMMON
    )
    assert ok.action == "accept"


def test_isolated_liq_short_mirrors() -> None:
    entry, lev = Decimal("65000"), Decimal("3")
    up = isolated_liq_price(entry=entry, lev=lev, side="sell")
    down = isolated_liq_price(entry=entry, lev=lev, side="buy")
    assert up > entry > down
    assert abs((up - entry) - (entry - down)) < Decimal("1")


def test_halt_room_is_a_warning_not_a_silent_shrink() -> None:
    """30% × 3x × 5% = 4.5% > day halt 3%: the tap is visible, the size is not cut."""
    h = Halts(start_equity=Decimal("100000"))
    room = h.remaining_frac(Decimal("100000"))
    assert room["day"] == Decimal("0.03")
    got = size_position(
        stop=Decimal("61750"),  # 5%
        deposit_share=Decimal("0.30"),
        max_stop_pct=Decimal("0.05"),
        day_halt_room=room["day"],
        **COMMON,
    )
    assert got.action == "accept"
    assert got.risk_frac > Decimal("0.03")
    assert got.risk_warning is True
    assert "day_halt" in got.warning


def test_operator_percent_strings_round_trip() -> None:
    assert parse_deposit_share("10") == Decimal("0.10")
    assert parse_deposit_share("30") == Decimal("0.30")
    assert parse_deposit_share("0.20") == Decimal("0.20")
    assert parse_max_stop_pct("5") == Decimal("0.05")
    assert parse_max_stop_pct("1") == Decimal("0.01")
    assert parse_max_stop_pct("0.03") == Decimal("0.03")
    with pytest.raises(ValueError):
        parse_deposit_share("0")
    with pytest.raises(ValueError):
        parse_max_stop_pct("6")
    with pytest.raises(ValueError):
        parse_max_stop_pct("0.005")
    cfg = RiskConfig(deposit_share_per_trade=Decimal("0.20"), max_stop_pct=Decimal("0.03"))
    again = RiskConfig.from_payload(cfg.to_payload())
    assert again.deposit_share_per_trade == Decimal("0.20")
    assert again.max_stop_pct == Decimal("0.03")
    # console percent boxes
    from_ui = RiskConfig.from_payload(
        {**RiskConfig().to_payload(), "deposit_share_per_trade": "20",
         "max_stop_pct": "4", "config_id": ""}
    )
    assert from_ui.deposit_share_per_trade == Decimal("0.20")
    assert from_ui.max_stop_pct == Decimal("0.04")


def test_risk_config_rejects_stop_pct_outside_one_to_five() -> None:
    with pytest.raises(ValueError, match="max_stop_pct"):
        RiskConfig(max_stop_pct=Decimal("0.06"))
    with pytest.raises(ValueError, match="max_stop_pct"):
        RiskConfig(max_stop_pct=Decimal("0"))


def test_console_accepts_percent_boxes(tmp_path: Path) -> None:
    from capitalizator.ops.console import ConsoleApp
    from capitalizator.ops.vault import init_vault

    app = ConsoleApp(init_vault(tmp_path / "v"))
    out = app.set_risk({"deposit_share_per_trade": "20", "max_stop_pct": "4"}, ack=True)
    assert Decimal(out["risk_config"]["deposit_share_per_trade"]) == Decimal("0.20")
    assert Decimal(out["risk_config"]["max_stop_pct"]) == Decimal("0.04")


def test_ops_page_has_two_dedicated_percent_boxes() -> None:
    page = render_ops_html(
        token="tok",
        status={},
        risk={"risk_config": RiskConfig().to_payload()},
        sessions={},
        universe={},
        commands=[],
        meta={},
    )
    assert "knob-deposit-share" in page
    assert "knob-max-stop" in page
    assert "deposit_share_per_trade" in page
    assert "max_stop_pct" in page
    # shown as percent, not the stored fraction
    assert "value='10'" in page
    assert "value='5'" in page
    assert "Доля депозита в сделку" in page
    assert "Максимальный стоп" in page
    assert "max_stop_pct" in RISK_HINTS
