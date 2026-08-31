"""Raw author posts. No weight. No Telegram."""

from capitalizator.authors.ingest import AuthorCall, AuthorsIngest
from capitalizator.authors.parse import AuthorParse, ParsedCall
from capitalizator.authors.resolve import AuthorsResolve, ResolveRule
from capitalizator.authors.score import author_accepts, weight

__all__ = [
    "AuthorCall",
    "AuthorParse",
    "AuthorsIngest",
    "AuthorsResolve",
    "ParsedCall",
    "ResolveRule",
    "author_accepts",
    "weight",
]
