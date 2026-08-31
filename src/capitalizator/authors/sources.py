"""Load infra/authors/sources.yaml. Telegram is forbidden."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ALLOWED_KINDS = ("rss", "reddit_json", "tradingview_own")
FORBIDDEN_KINDS = ("telegram", "scrape", "tip")


class SourcesError(ValueError):
    """Author source list is illegal."""


@dataclass(frozen=True)
class AuthorSource:
    source_id: str
    kind: str
    url: str
    tos_ok: bool


@dataclass(frozen=True)
class SourceBook:
    allowed_kinds: tuple[str, ...]
    forbidden_kinds: tuple[str, ...]
    sources: tuple[AuthorSource, ...]


def default_sources_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "authors" / "sources.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("infra/authors/sources.yaml not found")


def load_sources(path: Path | None = None) -> SourceBook:
    raw = yaml.safe_load((path or default_sources_path()).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SourcesError("sources.yaml must be a mapping")
    allowed = tuple(str(x) for x in raw.get("allowed_kinds") or [])
    forbidden = tuple(str(x) for x in raw.get("forbidden_kinds") or [])
    if set(allowed) != set(ALLOWED_KINDS):
        raise SourcesError("allowed_kinds must stay the PHASE-BUILD set")
    if "telegram" not in forbidden:
        raise SourcesError("telegram must stay forbidden")
    rows: list[AuthorSource] = []
    for item in raw.get("sources") or []:
        if not isinstance(item, dict):
            raise SourcesError("source row must be a mapping")
        kind = str(item.get("kind") or "")
        if kind in FORBIDDEN_KINDS or kind in forbidden:
            raise SourcesError(f"forbidden source kind: {kind}")
        if kind not in allowed:
            raise SourcesError(f"unknown source kind: {kind}")
        if item.get("tos_ok") is not True:
            raise SourcesError("tos_ok must be true")
        url = str(item.get("url") or "").strip()
        if not url.startswith("https://"):
            raise SourcesError("source url must be https")
        sid = str(item.get("id") or "").strip()
        if not sid:
            raise SourcesError("source id is required")
        rows.append(AuthorSource(source_id=sid, kind=kind, url=url, tos_ok=True))
    extra = set(raw) - {"allowed_kinds", "forbidden_kinds", "sources"}
    if extra:
        raise SourcesError(f"unknown keys: {sorted(extra)}")
    return SourceBook(allowed_kinds=allowed, forbidden_kinds=forbidden, sources=tuple(rows))
