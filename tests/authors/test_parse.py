"""2.12.1 — parse requires claims+horizon+known_at. Does not invent 50 posts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capitalizator.authors.ingest import AuthorCall, AuthorsIngest
from capitalizator.authors.parse import AuthorParse, AuthorParseError
from capitalizator.ops.check_author_parsed import main as check_author_parsed

TS = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _raw(*, claims: str = "", horizon: str = "") -> str:
    extra = ""
    if claims:
        extra += f',"claims":{claims}'
    if horizon:
        extra += f',"horizon":"{horizon}"'
    return (
        '{"author_id":"a","ts":"2026-08-31T12:00:00Z","source":"rss",'
        f'"text":"BTC long tomorrow","known_at":"2026-08-31T12:00:00Z"{extra}}}\n'
    )


def test_free_text_without_claims_is_not_parsed() -> None:
    call = AuthorCall(
        author_id="a",
        ts=TS,
        source="rss",
        text="BTC long 1h",
        known_at=TS,
    )
    assert AuthorParse().parse(call) is None


def test_structured_row_is_parsed() -> None:
    call = AuthorCall(
        author_id="a",
        ts=TS,
        source="rss",
        text="unit fixture",
        known_at=TS,
        claims=("BTCUSDT up",),
        horizon="1h",
    )
    got = AuthorParse().parse(call)
    assert got is not None
    assert got.claims == ("BTCUSDT up",)
    assert got.horizon == "1h"
    assert got.known_at == TS


def test_bad_horizon_raises() -> None:
    call = AuthorCall(
        author_id="a",
        ts=TS,
        source="rss",
        text="x",
        known_at=TS,
        claims=("up",),
        horizon="soon",
    )
    with pytest.raises(AuthorParseError, match="horizon"):
        AuthorParse().parse(call)


def test_jsonl_counts_only_parsed(tmp_path: Path) -> None:
    path = tmp_path / "mix.jsonl"
    path.write_text(_raw() + _raw(claims='["up"]', horizon="8s"), encoding="utf-8")
    raw = AuthorsIngest.from_jsonl(path)
    assert len(raw.rows) == 2
    assert len(AuthorParse().from_jsonl(path)) == 1


def test_check_author_parsed_below_min_is_fail(tmp_path: Path) -> None:
    path = tmp_path / "one.jsonl"
    path.write_text(_raw(claims='["up"]', horizon="1h"), encoding="utf-8")
    assert check_author_parsed(["--file", str(path), "--min", "50"]) == 2


def test_check_author_parsed_missing_file_is_fail(tmp_path: Path) -> None:
    assert check_author_parsed(["--file", str(tmp_path / "no.jsonl"), "--min", "50"]) == 2
