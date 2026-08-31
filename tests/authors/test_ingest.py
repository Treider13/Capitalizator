"""Author rows need two clocks. weight and Telegram are rejected. No invented week."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from capitalizator.authors.ingest import AuthorIngestError, AuthorsIngest
from capitalizator.authors.sources import SourcesError, load_sources
from capitalizator.ops.check_author_raw import main as check_author_raw


def test_repo_sources_have_no_live_rows() -> None:
    book = load_sources()
    assert book.sources == ()
    assert "telegram" in book.forbidden_kinds


def test_telegram_source_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "allowed_kinds": ["rss", "reddit_json", "tradingview_own"],
                "forbidden_kinds": ["telegram", "scrape", "tip"],
                "sources": [
                    {
                        "id": "tg",
                        "kind": "telegram",
                        "url": "https://t.me/x",
                        "tos_ok": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SourcesError, match="forbidden"):
        load_sources(path)


def test_weight_rejected(tmp_path: Path) -> None:
    path = tmp_path / "w.jsonl"
    path.write_text(
        '{"author_id":"a","ts":"2026-08-31T12:00:00Z","source":"rss",'
        '"text":"hi","known_at":"2026-08-31T12:00:00Z","weight":1}\n',
        encoding="utf-8",
    )
    with pytest.raises(AuthorIngestError, match="weight"):
        AuthorsIngest.from_jsonl(path)


def test_slice_before_known_at_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "one.jsonl"
    path.write_text(
        '{"author_id":"a","ts":"2026-08-31T12:00:00Z","source":"rss",'
        '"text":"hi","known_at":"2026-08-31T18:00:00Z"}\n',
        encoding="utf-8",
    )
    batch = AuthorsIngest.from_jsonl(path)
    assert batch.visible(datetime(2026, 8, 31, 12, 0, tzinfo=UTC)) == []
    assert len(batch.visible(datetime(2026, 8, 31, 18, 0, tzinfo=UTC))) == 1


def test_check_author_raw_below_min_is_fail(tmp_path: Path) -> None:
    path = tmp_path / "one.jsonl"
    path.write_text(
        '{"author_id":"a","ts":"2026-08-31T12:00:00Z","source":"rss",'
        '"text":"hi","known_at":"2026-08-31T12:00:00Z"}\n',
        encoding="utf-8",
    )
    assert check_author_raw(["--file", str(path), "--min", "20"]) == 2


def test_check_author_raw_missing_file_is_fail(tmp_path: Path) -> None:
    assert check_author_raw(["--file", str(tmp_path / "no.jsonl"), "--min", "20"]) == 2
