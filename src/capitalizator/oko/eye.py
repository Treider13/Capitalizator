"""OkoEye — one eye per desk. Holds the per-symbol organs and the Mirror.

Two moments, same as the desk clock:
  observe_window()  when the 8s ZLG clock closes: Retina + Shadow on the
                    frozen window, then the Passport learns from it (after).
  judge()           on the closed working bar, with CAV/ZLG known: Weather,
                    Forecast, Memory → Eyelid → Voice.
learn() when the touch outcome resolves. on_bar_close() feeds Weather.

Persistence: JSON under knowledge meta keys `oko:<organ>:<symbol>` and
`oko:mirror`. State is data, not code — reload replays the same numbers.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from capitalizator.oko.eyelid import OkoVerdict, blind_verdict, verdict
from capitalizator.oko.footprint import FootprintReport, combined_fingerprint
from capitalizator.oko.footprint import report as footprint_report
from capitalizator.oko.forecast import Sample, class_key, forecast
from capitalizator.oko.memory import ImmuneMemory
from capitalizator.oko.mirror import MIN_WINDOWS, MirrorReport
from capitalizator.oko.mirror import run as run_mirror
from capitalizator.oko.passport import Passport
from capitalizator.oko.retina import RawWindow, RetinaFrame, frame, observe_passport
from capitalizator.oko.shadow import ShadowReport, report
from capitalizator.oko.weather import Weather, WeatherReport
from capitalizator.types import require_utc
from capitalizator.zones.model import Bar

RECENT_WINDOWS = 20
MIRROR_EVERY = 5
META_PREFIX = "oko:"


class MetaStore(Protocol):
    def available(self) -> bool: ...

    def meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...

    def meta_prefix(self, prefix: str) -> dict[str, str]: ...


@dataclass(frozen=True)
class OkoWindow:
    symbol: str
    touch_id: str
    t0: datetime
    frame: RetinaFrame
    shadow: ShadowReport
    footprint: FootprintReport

    @property
    def fingerprint(self) -> tuple[int, ...]:
        return combined_fingerprint(self.shadow.fingerprint, self.footprint)

    @property
    def fingerprint_text(self) -> str:
        return "-".join(str(v) for v in self.fingerprint)


class OkoEye:
    def __init__(self, *, working_tf: str, mirror_seed: int = 0) -> None:
        if not working_tf:
            raise ValueError("working_tf required")
        self.working_tf = working_tf
        self.mirror_seed = mirror_seed
        self.passports: dict[str, Passport] = {}
        self.weathers: dict[str, Weather] = {}
        self.memories: dict[str, ImmuneMemory] = {}
        self.mirror: MirrorReport | None = None
        self.recent: dict[str, deque[RawWindow]] = {}
        self._since_mirror = 0

    def passport_for(self, symbol: str) -> Passport:
        if symbol not in self.passports:
            self.passports[symbol] = Passport(symbol)
        return self.passports[symbol]

    def weather_for(self, symbol: str) -> Weather:
        if symbol not in self.weathers:
            self.weathers[symbol] = Weather(symbol, tf=self.working_tf)
        return self.weathers[symbol]

    def memory_for(self, symbol: str) -> ImmuneMemory:
        if symbol not in self.memories:
            self.memories[symbol] = ImmuneMemory(symbol)
        return self.memories[symbol]

    @property
    def mirror_ok(self) -> bool:
        return self.mirror is not None and self.mirror.passed

    def observe_window(self, raw: RawWindow, *, touch_id: str, now: datetime) -> OkoWindow:
        passport = self.passport_for(raw.symbol)
        fr = frame(raw, passport)
        # churn of THIS window vs the symbol's norm, then the window teaches the norm
        probe = report(raw, fr)
        share = Decimal(str(probe.churn_share))
        sh = report(raw, fr, churn_z=passport.churn_excess(share))
        fp = footprint_report(raw, fr)
        observe_passport(raw, passport, fr)
        passport.observe_churn(share)
        bucket = self.recent.setdefault(raw.symbol, deque(maxlen=RECENT_WINDOWS))
        bucket.append(raw)
        self._since_mirror += 1
        if self._since_mirror >= MIRROR_EVERY and self.window_count() >= MIN_WINDOWS:
            self.run_mirror(now=now)
        return OkoWindow(
            symbol=raw.symbol, touch_id=touch_id, t0=raw.t0, frame=fr, shadow=sh, footprint=fp
        )

    def window_count(self) -> int:
        return sum(len(rows) for rows in self.recent.values())

    def run_mirror(self, *, now: datetime) -> MirrorReport:
        windows = [raw for rows in self.recent.values() for raw in rows]
        self.mirror = run_mirror(
            windows, self.passport_for, seed=self.mirror_seed, now=require_utc(now)
        )
        self._since_mirror = 0
        return self.mirror

    def on_bar_close(self, bar: Bar) -> float | None:
        if bar.tf != self.working_tf:
            return None
        return self.weather_for(bar.symbol).update(bar)

    def weather_report(self, symbol: str) -> WeatherReport:
        return self.weather_for(symbol).report()

    def judge(
        self,
        *,
        idea: str,
        zone_side: str,
        window: OkoWindow | None,
        cav: str | None,
        zlg: str | None,
        samples: Iterable[Sample],
        symbol: str | None = None,
    ) -> OkoVerdict:
        """window=None: the book was not ready at the print. Voice 0, label UNKNOWN."""
        name = window.symbol if window is not None else symbol
        if not name:
            raise ValueError("judge needs a window or a symbol")
        weather = self.weather_report(name)
        footprint = None if window is None else window.footprint.label
        key = class_key(idea=idea, cav=cav, zlg=zlg, regime=weather.regime, footprint=footprint)
        fc = forecast(samples, symbol=name, key=key)
        if window is None:
            return blind_verdict(weather=weather, forecast=fc)
        rec = self.memory_for(name).recognise(window.fingerprint, idea=idea)
        passport = self.passport_for(name)
        oi_after = window.frame.oi_after
        funding = window.frame.funding
        return verdict(
            idea=idea,
            zone_side=zone_side,
            shadow=window.shadow,
            footprint=window.footprint,
            weather=weather,
            forecast=fc,
            recognition=rec,
            mirror_ok=self.mirror_ok,
            oi_peak=None if oi_after is None else passport.oi_peak(oi_after),
            funding_top5=None if funding is None else passport.funding_top5(funding),
        )

    def learn(
        self,
        *,
        symbol: str,
        fingerprint: Sequence[int],
        idea: str,
        outcome: str,
        ts: datetime,
    ) -> bool:
        row = self.memory_for(symbol).learn(fingerprint, idea=idea, outcome=outcome, ts=ts)
        return row is not None

    def save(self, store: MetaStore, *, symbols: Iterable[str] | None = None) -> None:
        if not store.available():
            return
        names = (
            set(symbols)
            if symbols is not None
            else (set(self.passports) | set(self.weathers) | set(self.memories))
        )
        for symbol in sorted(names):
            if symbol in self.passports:
                store.set_meta(
                    f"{META_PREFIX}passport:{symbol}", _dump(self.passports[symbol].to_dict())
                )
            if symbol in self.weathers:
                store.set_meta(
                    f"{META_PREFIX}weather:{symbol}", _dump(self.weathers[symbol].to_dict())
                )
            if symbol in self.memories:
                store.set_meta(
                    f"{META_PREFIX}memory:{symbol}", _dump(self.memories[symbol].to_dict())
                )
        if self.mirror is not None:
            store.set_meta(f"{META_PREFIX}mirror", _dump(self.mirror.to_dict()))

    def load(self, store: MetaStore) -> int:
        """Rebuild organs from meta. Returns the number of keys read.

        One corrupt organ is dropped and reported in `load_errors` (the desk shows
        it); it never stops the desk from starting — the organ simply starts empty
        and learns again. Memory rows from before the Footprint organ are migrated.
        """
        if not store.available():
            return 0
        rows = store.meta_prefix(META_PREFIX)
        self.load_errors: dict[str, str] = {}
        for key, raw in sorted(rows.items()):
            parts = key[len(META_PREFIX) :].split(":", 1)
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("not a mapping")
                if parts[0] == "mirror":
                    self.mirror = MirrorReport.from_dict(payload)
                    continue
                if len(parts) != 2 or not parts[1]:
                    raise ValueError("key without symbol")
                organ, symbol = parts
                if organ == "passport":
                    self.passports[symbol] = Passport.from_dict(payload)
                elif organ == "weather":
                    weather = Weather.from_dict(payload)
                    if weather.tf != self.working_tf:
                        raise ValueError(f"weather tf {weather.tf} != {self.working_tf}")
                    self.weathers[symbol] = weather
                elif organ == "memory":
                    mem = ImmuneMemory.from_dict(payload)
                    self.memories[symbol] = mem
                    if mem.migrated or mem.skipped:
                        self.load_errors[key] = (
                            f"memory migrated={mem.migrated} skipped={mem.skipped}"
                        )
                else:
                    raise ValueError(f"unknown organ: {organ}")
            except (ValueError, KeyError, TypeError) as exc:
                self.load_errors[key] = str(exc)
        return len(rows)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=_default)


def _default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"not serialisable: {type(value).__name__}")
