"""Whale voice is a filter, not an entry. No Hyperliquid ingest yet."""

from capitalizator.whales.fragility import forbid_new_long
from capitalizator.whales.no_single import sole_whale, whale_accepts
from capitalizator.whales.pit import WhalePit

__all__ = ["WhalePit", "forbid_new_long", "sole_whale", "whale_accepts"]
