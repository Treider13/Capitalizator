"""Diagnostics retain gate distinctions and never treat a display status as permission."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest
from tests.fusion.daily_fixtures import seed_daily
from tests.fusion.test_contract_runtime import account, block, contract, instrument, register

from capitalizator.fusion.config import Config
from capitalizator.fusion.diagnose import decision_sample, summarize
from capitalizator.fusion.engine import Engine, Shared
from capitalizator.fusion.store import Store


def test_read_only_diagnostic_does_not_create_missing_database(tmp_path):
    path = tmp_path / "does-not-exist.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        decision_sample(path)
    assert not path.exists()


def test_journal_sample_is_bounded_and_not_dominated_by_pressure_payloads(tmp_path):
    store = Store(tmp_path / "db")
    try:
        for i in range(20):
            store.decision(i, "BTCUSDT", "atlas", {"reason": "sweep_required"})
        store.decision(21, "SOLUSDT", "contract_expired", {"reason": "entry_not_authorized"})
        store.decision(22, "BTCUSDT", "pressure_observation", {"reason": "collecting_baseline"})
        result = decision_sample(tmp_path / "db", limit=3)
        assert result["records"] == 3
        assert result["reasons"] == {
            "SOLUSDT": {"contract_expired:entry_not_authorized": 1},
            "BTCUSDT": {"atlas:sweep_required": 1},
        }
    finally:
        store.close()


def test_compact_report_separates_books_news_pause_and_model():
    cfg = Config(symbols=("XAUUSDT", "BTCUSDT"))
    good = {"valid": True, "book_at": 99, "exchange_at": 99, "spread_bps": 2, "imbalance": 0.2}
    status = {
        "at": 100,
        "config": asdict(cfg),
        "mode": "demo",
        "paused": True,
        "active_model_report": {"passed": False},
        "markets": {s: {"cross_market": {"linear": good}} for s in cfg.symbols},
        "news": {"coverage": {"XAUUSDT": {"ok": True, "at": 0}}},
    }
    result = summarize(status, {})
    assert result["paused"]
    assert result["model_report"]["passed"] is False
    assert result["pairs"]["XAUUSDT"]["book_checks"]["Buy"] == "ready"
    assert result["pairs"]["BTCUSDT"]["book_checks"]["Buy"] == "spot_not_ready"
    status["at"] = 300
    assert not summarize(status, {})["pairs"]["XAUUSDT"]["news_ok"]


def test_expired_contract_records_pause_and_news_without_changing_admission(tmp_path):
    store = Store(tmp_path / "db")
    try:
        shared = Shared()
        shared.paused = True
        shared.news_required = True
        shared.news_coverage = {"SOLUSDT": {"ok": False}}
        engine = Engine("SOLUSDT", store, shared, Config(), variant="B")
        engine.contract = contract("SOLUSDT")
        register(store, engine.contract)
        account(store)
        seed_daily(engine.market)
        engine._reserve_entry(block(), None, instrument("SOLUSDT"), "demo", False, 0.001)
        body = json.loads(
            store.rows("SELECT body FROM decisions ORDER BY id DESC LIMIT 1")[0]["body"]
        )
        assert body["reason"] == "entry_not_authorized"
        assert {"paused", "broker_not_ready", "news_coverage_unavailable"} <= set(body["blockers"])
        assert not store.rows("SELECT * FROM orders")
    finally:
        store.close()
