"""D-06/D-09/D-10/D-11/D-12/D-13: risk gates are wired, persistent and sized from equity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.exec.ev_gate import evaluate, expected_funding
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.risk.account import Account, PersistentBudget, session_key
from capitalizator.risk.config import RiskConfig, load_risk_config, save_risk_config
from capitalizator.risk.halts import Halts
from capitalizator.risk.schema import Intent, RiskEngine
from capitalizator.risk.sizing import size_position
from capitalizator.signer.process import unsigned_from_intent, validate_queue_payload

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def _intent(symbol: str = "BTCUSDT", qty: str | None = "0.5") -> Intent:
    return Intent(
        symbol=symbol, side="buy", entry=Decimal("65000"), stop=Decimal("64300"),
        tp=Decimal("66400"), tag="bounce", qty=None if qty is None else Decimal(qty),
    )


# --- RiskConfig ------------------------------------------------------------------
def test_risk_config_defaults_and_round_trip(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "d"))
    cfg = load_risk_config(kn)
    assert cfg == RiskConfig()
    assert cfg.target_risk_pct == Decimal("0.01") and cfg.max_lev == Decimal("3")
    nxt = cfg.with_changes(deposit_share_per_trade=Decimal("0.05"), fee_multiple_min=Decimal("8"))
    assert nxt.version == 2 and nxt.config_id != cfg.config_id
    with pytest.raises(ValueError, match="ack"):
        save_risk_config(kn, nxt, ack=False)
    save_risk_config(kn, nxt, ack=True)
    assert load_risk_config(kn) == nxt
    assert any('"k":"risk_config"' in link.payload for link in kn.links())
    kn.close()


@pytest.mark.parametrize(
    "bad",
    [
        {"deposit_share_per_trade": Decimal("0")},
        {"target_risk_pct": Decimal("0.06")},
        {"max_lev": Decimal("11")},
        {"day_halt": Decimal("0.03")},
        {"fee_multiple_min": Decimal("0.5")},
        {"stop_mode": "magic"},
    ],
)
def test_risk_config_rejects_nonsense(bad: dict) -> None:
    with pytest.raises(ValueError):
        RiskConfig(**bad)


def test_law_8_implied_risk() -> None:
    cfg = RiskConfig(deposit_share_per_trade=Decimal("0.2"), max_lev=Decimal("3"))
    assert cfg.implied_risk(lev=Decimal("3"), stop_frac=Decimal("0.04")) == Decimal("0.024")
    # 5x is above the phase ceiling (ARCHITECTURE-AZ §10 п.3) until a human raises phase.yaml
    with pytest.raises(ValueError, match="phase.yaml"):
        RiskConfig(max_lev=Decimal("5"))


# --- sizing ----------------------------------------------------------------------
def test_size_position_binding_constraints() -> None:
    common = dict(
        equity=Decimal("100000"), entry=Decimal("65000"), lev=Decimal("3"),
        target_risk=Decimal("0.01"), deposit_share=Decimal("0.10"),
        qty_step=Decimal("0.001"), min_qty=Decimal("0.001"), min_notional=Decimal("5"),
    )
    # wide stop (700 USDT): risk budget allows 1.43 BTC but 10% margin × 3x = 0.461 BTC binds
    wide = size_position(stop=Decimal("64300"), **common)
    assert wide.action == "accept" and wide.binding == "deposit_share"
    assert wide.qty == Decimal("0.461") and wide.margin <= Decimal("10000")
    assert wide.risk_frac < Decimal("0.01")
    # tight stop (65 USDT = 0.1%): risk budget binds → 15.384 BTC would be too much margin?
    tight = size_position(stop=Decimal("64935"), **common)
    assert tight.binding in {"deposit_share", "cap_margin"}
    assert tight.margin <= Decimal("10000")
    # tiny equity → below min notional → reject, not 0.001
    small = size_position(stop=Decimal("64300"), **{**common, "equity": Decimal("10")})
    assert small.action == "reject" and small.binding == "min_qty"
    with pytest.raises(ValueError):
        size_position(stop=Decimal("65000"), **common)


def test_size_position_never_raises_leverage() -> None:
    got = size_position(
        equity=Decimal("100000"), entry=Decimal("65000"), stop=Decimal("64300"),
        lev=Decimal("5"), target_risk=Decimal("0.01"), deposit_share=Decimal("0.10"),
        qty_step=Decimal("0.001"), min_qty=Decimal("0.001"), min_notional=Decimal("5"),
        max_lev=Decimal("3"),
    )
    assert got.action == "reject" and got.binding == "max_lev"


# --- EV gate ---------------------------------------------------------------------
def test_ev_gate_refuses_when_fees_exceed_r() -> None:
    # the audit case: 0.9 USDT R on BTC, qty 0.001 → fee 0.04 = 44R
    got = evaluate(qty=Decimal("0.001"), entry=Decimal("100000.1"), stop=Decimal("100001.0"),
                   tick=Decimal("0.1"))
    assert got.ok is False and got.reason.startswith("fee_gt_r")
    assert got.r_net_3r < 0
    assert got.breakeven_winrate is not None and got.breakeven_winrate > 1


def test_ev_gate_accepts_when_r_covers_costs_and_reports_net() -> None:
    got = evaluate(qty=Decimal("0.461"), entry=Decimal("65000"), stop=Decimal("64300"),
                   tick=Decimal("0.1"), funding_rate=Decimal("0.0001"))
    assert got.ok is True and got.fee_multiple is not None and got.fee_multiple >= 5
    assert got.funding > 0  # one settlement inside a 2h hold on a 8h interval
    assert got.r_net_1r == got.r_gross - got.costs
    assert got.r_net_2r > got.r_net_1r > 0
    # break-even winrate for a 2R target is (R + c) / 3R, just above 1/3
    assert Decimal("0.33") < got.breakeven_winrate < Decimal("0.36")


def test_expected_funding_counts_settlements_in_window() -> None:
    assert expected_funding(notional=Decimal("1000"), funding_rate=Decimal("0.0001"),
                            hold_hours=Decimal("2"), interval_min=480) == Decimal("0.1")
    assert expected_funding(notional=Decimal("1000"), funding_rate=Decimal("-0.0002"),
                            hold_hours=Decimal("9"), interval_min=480) == Decimal("0.4")
    assert expected_funding(notional=Decimal("1000"), funding_rate=None,
                            hold_hours=Decimal("2"), interval_min=480) == 0


# --- RiskEngine / Halts / Budget -------------------------------------------------
def test_risk_engine_per_symbol_and_cap() -> None:
    eng = RiskEngine(max_open=2)
    eng.on_open(_intent("BTCUSDT"))
    assert eng.allow_entry("BTCUSDT") is False
    assert eng.allow_entry("ETHUSDT") is True
    with pytest.raises(ValueError, match="already"):
        eng.on_open(_intent("BTCUSDT"))  # add-to is not a thing
    eng.on_open(_intent("ETHUSDT"))
    assert eng.allow_entry("SOLUSDT") is False
    eng.on_flat("BTCUSDT")
    assert eng.allow_entry("SOLUSDT") is True
    assert eng._open_position is not None  # legacy view still works


def test_halts_day_halt_lifts_on_new_day_peak_needs_release() -> None:
    h = Halts(start_equity=Decimal("100000"))
    h.update(Decimal("96900"))  # −3.1% day
    assert h.halted and h.reason == "day"
    h.new_day(Decimal("96900"))
    assert not h.halted
    # peak kill is sticky: a fresh day/week does not lift −25% from the peak
    h = Halts(start_equity=Decimal("74000"), peak=Decimal("100000"))
    h.update(Decimal("74000"))  # day 0 / week 0 / −26% from peak
    assert h.halted and h.reason == "peak"
    h.new_day(Decimal("74000"))
    h.new_week(Decimal("74000"))
    assert h.halted  # sticky
    with pytest.raises(ValueError):
        h.release(ack=False)
    h.release(ack=True)
    assert not h.halted


def test_account_roll_budget_and_persistence(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "d"))
    cfg = RiskConfig(max_intents_per_session=2, max_open_positions=1)
    acct = Account.load(kn, cfg, now=NOW)
    assert acct.equity == cfg.paper_equity
    b = acct.budget(NOW)
    assert isinstance(b, PersistentBudget) and b.key == session_key(NOW)
    b.on_intent()
    b.on_intent()
    assert b.allow_entry() is False
    # next Moscow day → fresh budget; the old one is remembered on disk
    assert acct.budget(NOW + timedelta(days=1)).allow_entry() is True
    again = Account.load(kn, cfg, now=NOW)
    assert again.budget(NOW).n == 2  # survived the "restart"
    # open idea + pnl → equity, halts, persistence
    acct.on_open(_intent(), now=NOW, intent_id=7)
    assert acct.allow_entry("BTCUSDT") == (False, "position_open_same_symbol")
    assert acct.allow_entry("ETHUSDT") == (False, "max_open_positions")
    acct.apply_pnl(pnl=Decimal("-3500"), fees=Decimal("10"), funding=Decimal("0"), now=NOW)
    assert acct.halts.halted and acct.halts.reason == "day"
    assert acct.allow_entry("ETHUSDT")[1] == "halt:day"
    snap = json.loads(kn.meta("account"))
    assert snap["equity"] == "96490" and snap["halted"] is True
    assert snap["open"][0]["symbol"] == "BTCUSDT"
    reloaded = Account.load(kn, cfg, now=NOW)
    assert reloaded.equity == Decimal("96490") and reloaded.halts.halted
    acct.on_flat("BTCUSDT")
    assert acct.open == {} and acct.risk.allow_entry("BTCUSDT") is True
    kn.close()


def test_account_rejects_unsized_intent() -> None:
    acct = Account(config=RiskConfig())
    with pytest.raises(ValueError, match="sized"):
        acct.on_open(_intent(qty=None), now=NOW)


# --- signer refuses unsized intents on the live drain -----------------------------
def test_live_drain_refuses_unsized_intent() -> None:
    raw = {"symbol": "BTCUSDT", "side": "buy", "entry": "65000", "stop": "64300", "tp": "66400"}
    assert unsigned_from_intent(raw).qty == Decimal("0.001")  # bare helper keeps the fixture
    with pytest.raises(ValueError, match="not sized"):
        validate_queue_payload(raw)
    sized = validate_queue_payload({**raw, "qty": "0.461"})
    assert sized["qty"] == "0.461"
