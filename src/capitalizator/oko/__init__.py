"""ОКО — sixth jury voice with veto. Sees the book, names manipulation, abstains.

INVENTION-OKO.md. Seven layers: Passport → Retina → Shadow → Weather →
Forecast → Memory → Eyelid; Mirror tests Shadow on injected manipulation.
Labels and a Voice only. Never opens size, never raises size_mult above 1.
"""

from capitalizator.oko.eye import OkoEye, OkoWindow
from capitalizator.oko.eyelid import OkoVerdict, oko_opens_size
from capitalizator.oko.footprint import FootprintReport
from capitalizator.oko.forecast import ForecastReport
from capitalizator.oko.memory import ImmuneMemory
from capitalizator.oko.mirror import MirrorReport
from capitalizator.oko.passport import Passport
from capitalizator.oko.retina import RawWindow, RetinaFrame
from capitalizator.oko.shadow import ShadowReport
from capitalizator.oko.weather import Weather, WeatherReport

__all__ = [
    "FootprintReport",
    "ForecastReport",
    "ImmuneMemory",
    "MirrorReport",
    "OkoEye",
    "OkoVerdict",
    "OkoWindow",
    "Passport",
    "RawWindow",
    "RetinaFrame",
    "ShadowReport",
    "Weather",
    "WeatherReport",
    "oko_opens_size",
]
