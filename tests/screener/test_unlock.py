"""3.14.1 — team unlock today/tomorrow cuts. Empty calendar is not an invented row."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.news_macro.unlocks import UnlockError, Unlocks
from capitalizator.screener.filters import Screener

REPO_CSV = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "unlocks.csv"
HEADER = (
    "unlock_id,symbol,event_time_utc,known_at_utc,"
    "recipient_type,amount_tokens,amount_usd_est,source\n"
)
NOW = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)


def _write(path: Path, body: str) -> Path:
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_repo_calendar_is_header_only() -> None:
    book = Unlocks.load(REPO_CSV)
    assert book.rows == []
    assert book.team_blocks("BTCUSDT", NOW) is False
    assert book.team_blocks("SOLUSDT", NOW) is False


def test_missing_file_is_empty_not_invented(tmp_path: Path) -> None:
    book = Unlocks.load(tmp_path / "no.csv")
    assert book.rows == []
    assert book.team_tomorrow("BTCUSDT", NOW) is False


def test_team_tomorrow_sets_flag(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "btc-2026-09-01,BTCUSDT,2026-09-01T00:00:00Z,2026-08-20T12:00:00Z,team,1,1,fixture\n",
    )
    book = Unlocks.from_csv(path)
    assert book.team_tomorrow("BTCUSDT", NOW) is True
    assert book.team_today("BTCUSDT", NOW) is False
    assert book.team_blocks("BTCUSDT", NOW) is True
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            unlock_tomorrow=book.team_tomorrow("BTCUSDT", NOW),
        )
        is False
    )


def test_team_today_also_cuts(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "btc-2026-08-31,BTCUSDT,2026-08-31T00:00:00Z,2026-08-20T12:00:00Z,team,1,1,fixture\n",
    )
    book = Unlocks.from_csv(path)
    assert book.team_today("BTCUSDT", NOW) is True
    assert book.team_tomorrow("BTCUSDT", NOW) is False
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            unlock_today=True,
        )
        is False
    )


def test_investor_does_not_cut(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "btc-2026-09-01,BTCUSDT,2026-09-01T00:00:00Z,2026-08-20T12:00:00Z,investor,1,1,fixture\n",
    )
    book = Unlocks.from_csv(path)
    assert book.team_blocks("BTCUSDT", NOW) is False
    assert (
        Screener().ok(
            "BTCUSDT",
            spread_frac=Decimal("0.001"),
            typical_move=Decimal("0.01"),
            unlock_tomorrow=book.team_tomorrow("BTCUSDT", NOW),
        )
        is True
    )


def test_unknown_at_slice_is_invisible(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "btc-2026-09-01,BTCUSDT,2026-09-01T00:00:00Z,2026-09-01T12:00:00Z,team,1,1,fixture\n",
    )
    book = Unlocks.from_csv(path)
    assert book.visible(NOW) == []
    assert book.team_tomorrow("BTCUSDT", NOW) is False


def test_two_days_away_does_not_cut(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "btc-2026-09-02,BTCUSDT,2026-09-02T00:00:00Z,2026-08-20T12:00:00Z,team,1,1,fixture\n",
    )
    assert Unlocks.from_csv(path).team_blocks("BTCUSDT", NOW) is False


def test_other_symbol_does_not_cut_btc(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "sol-2026-09-01,SOLUSDT,2026-09-01T00:00:00Z,2026-08-20T12:00:00Z,team,1,1,fixture\n",
    )
    book = Unlocks.from_csv(path)
    assert book.team_tomorrow("SOLUSDT", NOW) is True
    assert book.team_tomorrow("BTCUSDT", NOW) is False


def test_unknown_recipient_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "u.csv",
        "x,BTCUSDT,2026-09-01T00:00:00Z,2026-08-20T12:00:00Z,insider,1,1,fixture\n",
    )
    with pytest.raises(UnlockError, match="recipient"):
        Unlocks.from_csv(path)


def test_module_has_no_short_signal() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "capitalizator" / "news_macro" / "unlocks.py"
    text = src.read_text(encoding="utf-8")
    assert "short" not in text.lower()
    assert "sell" not in text.lower()
    assert "side =" not in text
