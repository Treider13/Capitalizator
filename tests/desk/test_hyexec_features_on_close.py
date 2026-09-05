"""5m close stores a PIT feature row. Zones and jury stay on 15m."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from capitalizator.desk.bars import FEATURE_TFS
from capitalizator.desk.loop import DeskLoop
from capitalizator.desk.tape import close_due_bars
from capitalizator.hyexec.features import FeatureRow
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.vault import init_vault
from capitalizator.types import MarketEvent
from capitalizator.zones.config import KNOWN_TFS
from capitalizator.zones.model import Bar

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _desk(tmp_path: Path) -> DeskLoop:
    return DeskLoop(knowledge=open_knowledge(init_vault(tmp_path / "d")), user_mode="off")


def _bar(tf: str, close_ts: datetime, close: str) -> Bar:
    minutes = {"1m": 1, "5m": 5, "15m": 15}[tf]
    px = Decimal(close)
    return Bar(
        symbol="BTCUSDT",
        tf=tf,
        open_ts=close_ts - timedelta(minutes=minutes),
        close_ts=close_ts,
        open=px,
        high=px,
        low=px,
        close=px,
        volume=Decimal("1"),
    )


def _trade(ts: datetime, px: str) -> MarketEvent:
    return MarketEvent(
        stream="trades",
        exchange="bybit",
        symbol="BTCUSDT",
        exchange_ts=ts,
        recv_ts=ts,
        payload={"px": px, "qty": "1", "side": "buy"},
    )


def test_feature_buckets_are_not_zone_tfs() -> None:
    assert FEATURE_TFS == ("1m", "5m")
    assert "1m" not in KNOWN_TFS
    assert "5m" not in KNOWN_TFS


def test_desk_builder_includes_feature_tfs(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    st = desk.state_for("BTCUSDT")
    assert st.bar_builder is not None
    assert "1m" in st.bar_builder.tfs
    assert "5m" in st.bar_builder.tfs
    assert desk.config.structure_tfs == ("15m", "1h", "4h", "1d")
    assert "5m" not in desk.config.structure_tfs


def test_five_minute_close_stores_features_not_zone_bars(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    first = _bar("5m", T0 + timedelta(minutes=5), "98")
    second = _bar("5m", T0 + timedelta(minutes=10), "100")
    events = desk.on_bar_close(first) + desk.on_bar_close(second)
    st = desk.state_for("BTCUSDT")
    assert all(b.tf != "5m" for b in st.bars)
    assert [b.tf for b in st.feature_bars] == ["5m", "5m"]
    assert isinstance(st.last_features, FeatureRow)
    assert st.last_features.close_5m == Decimal("100")
    assert st.last_features.vector["ret_5m"] == Decimal("2") / Decimal("98")
    assert any(ev.get("event") == "hyexec_features" for ev in events)
    assert desk.hyexec_model_go is None


def test_five_minute_close_does_not_run_jury(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    events = desk.on_bar_close(_bar("5m", T0 + timedelta(minutes=5), "100"))
    assert not any(ev.get("event") in {"jury", "accord", "silence"} for ev in events)
    assert desk.state_for("BTCUSDT").state == "IDLE"


def test_live_builder_emits_five_minute_features(tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    st = desk.state_for("BTCUSDT")
    for i in range(12):
        desk.on_trade(_trade(T0 + timedelta(seconds=30 * i), str(100 + i)), [])
    events = close_due_bars(desk, "BTCUSDT", T0 + timedelta(minutes=6))
    assert st.last_features is not None
    assert st.last_features.close_5m is not None
    assert all(b.tf != "5m" for b in st.bars)
    assert any(ev.get("event") == "hyexec_features" for ev in events)
