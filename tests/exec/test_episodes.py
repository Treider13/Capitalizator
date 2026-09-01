"""Paper episode log. Empty is honest. mode is shadow|demo|micro|live."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capitalizator.exec.episodes import EpisodeLog


def test_empty_log_has_no_rows() -> None:
    assert EpisodeLog().for_date(datetime(2026, 8, 31, tzinfo=UTC).date()) == []


def test_append_demo_row() -> None:
    log = EpisodeLog()
    fill = datetime(2026, 8, 31, 14, 20, tzinfo=UTC)
    log.append(
        {
            "trade_id": "t1",
            "mode": "demo",
            "zone_id": "abc",
            "gesture": "pending",
            "fill": fill,
            "slip": "0",
            "fees": "0",
            "r": "0",
        }
    )
    rows = log.for_date(fill.date())
    assert len(rows) == 1
    assert rows[0]["mode"] == "demo"


def test_live_mode_accepted() -> None:
    log = EpisodeLog()
    fill = datetime(2026, 8, 31, tzinfo=UTC)
    log.append(
        {
            "trade_id": "t1",
            "mode": "live",
            "zone_id": "abc",
            "gesture": "pending",
            "fill": fill,
            "slip": "0",
            "fees": "0",
            "r": "0",
        }
    )
    assert log.rows[0]["mode"] == "live"


def test_grid_mode_rejected() -> None:
    with pytest.raises(ValueError, match="shadow|demo|micro|live"):
        EpisodeLog().append(
            {
                "trade_id": "t1",
                "mode": "grid",
                "zone_id": "abc",
                "gesture": "pending",
                "fill": datetime(2026, 8, 31, tzinfo=UTC),
                "slip": "0",
                "fees": "0",
                "r": "0",
            }
        )
