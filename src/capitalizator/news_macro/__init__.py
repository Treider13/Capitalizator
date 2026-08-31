"""Macro calendar with two clocks. No TG scrape."""

from typing import Any

__all__ = ["NewsIngest", "NewsRow", "NewsStore", "Unlocks", "UnlockRow"]


def __getattr__(name: str) -> Any:
    if name in {"NewsIngest", "NewsRow"}:
        from capitalizator.news_macro.ingest import NewsIngest, NewsRow

        return {"NewsIngest": NewsIngest, "NewsRow": NewsRow}[name]
    if name == "NewsStore":
        from capitalizator.news_macro.store import NewsStore

        return NewsStore
    if name in {"Unlocks", "UnlockRow"}:
        from capitalizator.news_macro.unlocks import UnlockRow, Unlocks

        return {"Unlocks": Unlocks, "UnlockRow": UnlockRow}[name]
    raise AttributeError(name)
