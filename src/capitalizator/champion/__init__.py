"""Drift detector on synthetic errors. No live champion swap."""

from capitalizator.champion.drift import PageHinkley
from capitalizator.champion.shadow_width import ShadowWidth

__all__ = ["PageHinkley", "ShadowWidth"]
