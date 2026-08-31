"""3.14.2 — empty prior is honest. n<5 is not our coefficient. Does not open size."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from capitalizator.news_macro.reaction import ReactionTable

REPO = Path(__file__).resolve().parents[2] / "infra" / "calendars" / "reaction_prior.csv"


def test_repo_prior_is_header_only() -> None:
    book = ReactionTable.load(REPO)
    assert book.rows == []
    assert book.our_coef("CPI", "trend") is None
    assert book.opens_size() is False


def test_missing_file_is_empty(tmp_path: Path) -> None:
    book = ReactionTable.load(tmp_path / "no.csv")
    assert book.rows == []
    assert book.opens_size() is False


def test_n_below_five_is_not_our_coef(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    path.write_text(
        "class,regime,horizon_min,mean_ret,n,source\n"
        "CPI,trend,60,0.01,4,paper\n",
        encoding="utf-8",
    )
    book = ReactionTable.from_csv(path)
    assert book.our_coef("CPI", "trend") is None
    assert book.opens_size() is False


def test_n_five_returns_our_number_but_still_no_size(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    path.write_text(
        "class,regime,horizon_min,mean_ret,n,source\n"
        "CPI,trend,60,0.01,5,ours\n",
        encoding="utf-8",
    )
    book = ReactionTable.from_csv(path)
    assert book.our_coef("CPI", "trend") == Decimal("0.01")
    assert book.opens_size() is False
