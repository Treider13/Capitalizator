"""Weekly universe proposal by rule; applied only by a human ack through the validator."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.screener.refresh import (
    META_APPLIED,
    META_PROPOSAL,
    apply_universe,
    propose,
    publish_proposal,
)
from capitalizator.screener.universe import load_universe, validate_universe

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
OLD = int((NOW - timedelta(days=400)).timestamp() * 1000)
NEW = int((NOW - timedelta(days=10)).timestamp() * 1000)


def _inst(symbol: str, *, launch: int = OLD, status: str = "Trading", **extra) -> dict:
    return {"symbol": symbol, "status": status, "launchTime": str(launch),
            "contractType": "LinearPerpetual", "quoteCoin": "USDT", **extra}


def _tick(symbol: str, turnover: str) -> dict:
    return {"symbol": symbol, "turnover24h": turnover}


CURRENT = validate_universe({"exchange": "bybit", "category": "linear",
                             "symbols": ["BTCUSDT", "ETHUSDT", "OLDUSDT", "SOLUSDT"]})


def test_top_n_by_turnover_majors_always_history_required() -> None:
    instruments = [
        _inst("BTCUSDT"), _inst("ETHUSDT"), _inst("SOLUSDT"), _inst("OLDUSDT"),
        _inst("NEWUSDT", launch=NEW), _inst("DEADUSDT", status="Delivering"),
        _inst("XRPUSDT"), _inst("BTCUSD", contractType="InversePerpetual", quoteCoin="USD"),
        _inst("ETH-26DEC25", contractType="LinearFutures"),
    ]
    tickers = [
        _tick("BTCUSDT", "100"), _tick("ETHUSDT", "1"), _tick("SOLUSDT", "50"),
        _tick("OLDUSDT", "0.5"), _tick("NEWUSDT", "999"), _tick("DEADUSDT", "999"),
        _tick("XRPUSDT", "40"),
    ]
    p = propose(now=NOW, instruments=instruments, tickers=tickers, current=CURRENT,
                size=4, hysteresis=0)
    # majors first, then by turnover: SOL (50) and XRP (40); NEW is too young, DEAD not trading
    assert p.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert p.added == ("XRPUSDT",) and p.dropped == ("OLDUSDT",)
    assert p.rejected["OLDUSDT"] == "rank_below_cut"
    assert p.ranked[0][0] == "BTCUSDT" and dict(p.ranked)["SOLUSDT"] == "50"
    payload = p.to_payload()
    assert payload["changes"] is True and len(payload["proposal_id"]) == 16
    # ETH has tiny turnover but is a major → still in
    assert "ETHUSDT" in p.symbols


def test_missing_major_or_bad_size_is_an_error() -> None:
    with pytest.raises(ValueError, match="major"):
        propose(now=NOW, instruments=[_inst("BTCUSDT")], tickers=[_tick("BTCUSDT", "1")],
                current=CURRENT, size=3)
    with pytest.raises(ValueError, match="size"):
        propose(now=NOW, instruments=[], tickers=[], current=CURRENT, size=1)


def test_publish_then_apply_rewrites_yaml_only_with_ack(tmp_path: Path) -> None:
    kn = open_knowledge(init_vault(tmp_path / "v"))
    yaml_path = tmp_path / "universe.yaml"
    yaml_path.write_text(yaml.safe_dump({"exchange": "bybit", "category": "linear",
                                         "symbols": ["BTCUSDT", "ETHUSDT", "OLDUSDT"]}))
    instruments = [_inst("BTCUSDT"), _inst("ETHUSDT"), _inst("SOLUSDT"), _inst("OLDUSDT")]
    tickers = [_tick("BTCUSDT", "9"), _tick("ETHUSDT", "8"), _tick("SOLUSDT", "7"),
               _tick("OLDUSDT", "1")]
    p = publish_proposal(kn, now=NOW, instruments=instruments, tickers=tickers,
                         universe_path=yaml_path, size=3, hysteresis=0)
    stored = json.loads(kn.meta(META_PROPOSAL))
    assert stored["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"] and stored["dropped"] == ["OLDUSDT"]
    with pytest.raises(ValueError, match="ack"):
        apply_universe(kn, proposal_id=p.proposal_id, ack=False, now=NOW, universe_path=yaml_path)
    with pytest.raises(ValueError, match="proposal_id"):
        apply_universe(kn, proposal_id="nope", ack=True, now=NOW, universe_path=yaml_path)
    assert load_universe(yaml_path).symbols == ("BTCUSDT", "ETHUSDT", "OLDUSDT")  # untouched
    universe = apply_universe(kn, proposal_id=p.proposal_id, ack=True, now=NOW,
                              universe_path=yaml_path)
    assert universe.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert load_universe(yaml_path).symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert "proposal_id=" in yaml_path.read_text()
    assert json.loads(kn.meta(META_APPLIED))["proposal_id"] == p.proposal_id
    assert any('"k":"universe"' in link.payload for link in kn.links())
    kn.close()
