"""Closed-bar multi-timeframe structure; confirmed pivots and ordered swing anchors."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from capitalizator.card.sweep import fractals
from capitalizator.desk.bars import TF_MINUTES
from capitalizator.fusion.context import geometry, session_windows
from capitalizator.zones.model import Bar

TFS = ("1m", "5m", "15m", "1h", "4h")
PAIRS = (("15m", "1m"), ("1h", "5m"), ("4h", "15m"))


def candle(bar: Bar) -> dict[str, Any]:
    return {
        "at": bar.open_ts.timestamp(),
        "end": bar.close_ts.timestamp(),
        **{k: float(getattr(bar, k)) for k in ("open", "high", "low", "close", "volume")},
    }


def parse_history(symbol: str, tf: str, rows: list[Any], known_at: float) -> list[Bar]:
    result = []
    if any(not isinstance(row, list) or len(row) < 6 for row in rows):
        raise ValueError("historical candle schema invalid")
    for row in sorted(rows, key=lambda r: int(r[0])):
        start = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
        end = start + timedelta(minutes=TF_MINUTES[tf])
        if end.timestamp() > known_at:
            continue
        values = [Decimal(str(v)) for v in row[1:6]]
        if (
            not all(v.is_finite() for v in values)
            or min(values[:4]) <= 0
            or values[4] < 0
            or not values[2] <= values[0] <= values[1]
            or not values[2] <= values[3] <= values[1]
        ):
            raise ValueError("invalid historical OHLCV")
        if int(row[0]) % (TF_MINUTES[tf] * 60000):
            raise ValueError("historical candle not aligned to timeframe")
        result.append(
            Bar(
                symbol=symbol,
                tf=tf,
                open_ts=start,
                close_ts=end,
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[5]),
            )
        )
    return result


class Structure:
    def __init__(self) -> None:
        self.bars: dict[str, deque[Bar]] = {tf: deque(maxlen=512) for tf in TFS}
        self.cache: dict[str, dict[str, Any]] = {}
        self.previous_break: dict[str, int] = {}
        self.revision = 0

    def add(self, bar: Bar, tick: float) -> None:
        series = self.bars[bar.tf]
        if series and bar.close_ts <= series[-1].close_ts:
            return
        series.append(bar)
        self._calculate(bar.tf, tick)

    def seed(self, bars: list[Bar], tick: float) -> None:
        for tf in TFS:
            current = {b.open_ts: b for b in self.bars[tf]}
            for b in bars:
                if b.tf == tf:
                    # Authoritative REST closed candles repair partial first live buckets.
                    current[b.open_ts] = b
            if current:
                self.bars[tf] = deque(
                    sorted(current.values(), key=lambda b: b.open_ts)[-512:], maxlen=512
                )
                self._calculate(tf, tick)

    def _calculate(self, tf: str, tick: float) -> None:
        bars = list(self.bars[tf])
        g = geometry(bars, tick)
        hi, lo = fractals(bars, n=2)
        trend = g.get("trend")
        highs = [
            {
                "at": bars[i].open_ts.timestamp(),
                "price": float(bars[i].high),
                "known_at": bars[i + 2].close_ts.timestamp(),
            }
            for i in hi
        ]
        lows = [
            {
                "at": bars[i].open_ts.timestamp(),
                "price": float(bars[i].low),
                "known_at": bars[i + 2].close_ts.timestamp(),
            }
            for i in lo
        ]
        anchors = None
        if trend == 1 and highs:
            prior = [p for p in lows if p["at"] < highs[-1]["at"]]
            if prior:
                anchors = {
                    "low": prior[-1]["price"],
                    "high": highs[-1]["price"],
                    "from": prior[-1]["at"],
                    "to": highs[-1]["at"],
                }
        elif trend == -1 and lows:
            prior = [p for p in highs if p["at"] < lows[-1]["at"]]
            if prior:
                anchors = {
                    "low": lows[-1]["price"],
                    "high": prior[-1]["price"],
                    "from": prior[-1]["at"],
                    "to": lows[-1]["at"],
                }
        low = lows[-1]["price"] if lows else None
        high = highs[-1]["price"] if highs else None
        close = float(bars[-1].close)
        direction = (
            1 if high is not None and close > high else -1 if low is not None and close < low else 0
        )
        choch = (
            direction if direction and self.previous_break.get(tf, direction) != direction else 0
        )
        if direction:
            self.previous_break[tf] = direction
        zones = []
        # Active three-candle inefficiencies; keep only their still-unfilled interval.
        for i in range(2, len(bars)):
            a, b = bars[i - 2], bars[i]
            side = 1 if b.low > a.high else -1 if b.high < a.low else 0
            if not side:
                continue
            bottom, top = (
                (float(a.high), float(b.low)) if side == 1 else (float(b.high), float(a.low))
            )
            for later in bars[i + 1 :]:
                if side == 1:
                    top = min(top, float(later.low))
                else:
                    bottom = max(bottom, float(later.high))
                if bottom >= top:
                    break
            if bottom < top:
                zones.append(
                    {
                        "kind": "FVG",
                        "side": side,
                        "low": bottom,
                        "high": top,
                        "at": b.close_ts.timestamp(),
                    }
                )
        self.cache[tf] = {
            "tf": tf,
            "at": bars[-1].close_ts.timestamp(),
            "trend": trend,
            "support": low,
            "resistance": high,
            "swings": anchors,
            "highs": highs[-20:],
            "lows": lows[-20:],
            "bos": direction,
            "choch": choch,
            "geometry": g,
            "zones": zones[-30:],
            "candles": [candle(b) for b in bars],
            "sessions": session_windows(bars[0].open_ts.timestamp(), bars[-1].close_ts.timestamp()),
            "bars": len(bars),
        }
        self.revision += 1

    def pair(self, side: int, price: float, low: float, high: float, at: float) -> dict[str, Any]:
        reasons = []
        for htf, ltf in PAIRS:
            h, lower = self.cache.get(htf), self.cache.get(ltf)
            if not h or not lower or h["trend"] is None:
                reasons.append(f"{htf}/{ltf}:warming")
                continue
            if not (
                0 <= at - h["at"] <= TF_MINUTES[htf] * 60
                and 0 <= at - lower["at"] <= TF_MINUTES[ltf] * 60
            ):
                reasons.append(f"{htf}/{ltf}:stale")
                continue
            support, resistance = h["support"], h["resistance"]
            if support is None or resistance is None or support >= resistance:
                continue
            trend = h["trend"]
            if trend not in (0, side):
                continue
            anchor = h["swings"] if trend else {"low": support, "high": resistance}
            if not anchor or anchor["high"] <= anchor["low"]:
                continue
            span = anchor["high"] - anchor["low"]
            retracement = (
                (anchor["high"] - price) if side == 1 else (price - anchor["low"])
            ) / span
            if not 0.5 <= retracement <= 1:
                continue
            # HTF POI can be an unfilled gap, OB, or confirmed support/resistance.
            zones = list(h["zones"])
            ob = h["geometry"].get("order_block_zone")
            if ob:
                zones.append({**ob, "kind": "OB"})
            level = support if side == 1 else resistance
            touched = low <= level <= high
            poi = {"kind": "swing", "low": level, "high": level} if touched else None
            for z in zones:
                if z["side"] == side and low <= z["high"] and high >= z["low"]:
                    poi = z
                    break
            if poi is None:
                continue
            # A local closed-bar swing must actually be swept and reclaimed now.
            local = lower["support"] if side == 1 else lower["resistance"]
            swept = local is not None and (
                low < local < price if side == 1 else price < local < high
            )
            if not swept:
                continue
            return {
                "allowed": True,
                "htf": htf,
                "ltf": ltf,
                "trend": trend,
                "regime": "range" if trend == 0 else "trend",
                "poi": poi,
                "swept_level": local,
                "retracement": retracement,
                "anchors": anchor,
                "ote": [anchor["high"] - 0.786 * span, anchor["high"] - 0.618 * span]
                if side == 1
                else [anchor["low"] + 0.618 * span, anchor["low"] + 0.786 * span],
                "target": resistance if side == 1 else support,
                "known_at": max(h["at"], lower["at"]),
            }
        return {"allowed": False, "reason": "htf_ltf_unconfirmed", "diagnostics": reasons}
