"""Build a 5–7 atom CardLive. At least one minus. Does not send. No Telegram."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from capitalizator.card.gex import OptionRow
from capitalizator.card.labels import BLabels, compute_b_labels
from capitalizator.card.live import CardLive, VolumeSnapshot
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.screener.universe import load_desk_universe
from capitalizator.types import require_utc
from capitalizator.zones.model import Bar

IMMINENT_HOURS = 2


def from_news(
    *,
    symbol: str,
    now: datetime,
    calendar: tuple[NewsRow, ...],
    volume: VolumeSnapshot | None = None,
    bars: Sequence[Bar] | None = None,
    option_chain: Sequence[OptionRow] | None = None,
    fib_zone: str | None = None,
    fib_level: str | None = None,
    rsi_htf: str | None = None,
    gex_bg: str | None = None,
    fvg_status: str | None = None,
    sweep_status: str | None = None,
    ob_status: str | None = None,
    bos_status: str | None = None,
    venue: str = "perp",
    universe: Sequence[str] | None = None,
    spot_acked: bool = False,
) -> CardLive:
    when = require_utc(now)
    vol = volume or VolumeSnapshot()
    labels = (
        compute_b_labels(bars, chain=option_chain)
        if bars
        else BLabels()
    )
    names = frozenset(universe) if universe is not None else frozenset(load_desk_universe().symbols)
    hits = [
        row
        for row in calendar
        if row.known_at <= when
        and (not row.assets or symbol in row.assets or "BTCUSDT" in row.assets)
    ]
    imminent = [
        row
        for row in hits
        if row.event_class in {"CPI", "FOMC"}
        and timedelta_hours(row.event_time, when) <= IMMINENT_HOURS
        and row.event_time >= when
    ]
    negative_coin = [
        row
        for row in hits
        if symbol in row.assets
        and row.event_class in {"HACK", "SEC", "OTHER"}
        and _negative(row)
    ]
    listing = [
        row
        for row in calendar
        if row.known_at <= when
        and row.event_class == "LISTING"
        and symbol in row.assets
        and symbol not in names
    ]

    pluses: list[str]
    minuses: list[str]
    bearing: str
    macro = Decimal("1")

    if imminent:
        row = imminent[0]
        bearing = "veto"
        pluses = (
            f"calendar_{row.event_class}",
            "known_at_set",
            "window_marked",
        )
        minuses = (
            "fomc_inside_2h",
            "first_print_unplayed",
        )
    elif negative_coin:
        row = negative_coin[0]
        bearing = "veto"
        pluses = (
            f"class_{row.event_class}",
            "source_official",
            "asset_matched",
        )
        minuses = (
            "coin_negative",
            "thesis_dead",
        )
    elif listing:
        venue = "spot_proposal"
        pluses = (
            "listing_seen",
            "official_calendar",
            "listing_base_rate_low",
        )
        if spot_acked:
            bearing = "propose"
            minuses = ("not_in_universe",)
        else:
            bearing = "hold"
            minuses = ("not_in_universe", "no_spot_ack")
    else:
        rvol = Decimal(vol.rvol) if vol.rvol else Decimal("0")
        pluses = (
            "session_profile",
            "htf_bias_read",
            "official_calendar_quiet",
        )
        minuses = (
            "base_rate_unknown",
        )
        if rvol > 2:
            pluses = (*pluses, "rvol_above_2")
            bearing = "propose"
        else:
            pluses = (*pluses, "rvol_normal")
            bearing = "propose"
        if any(
            row.event_class in {"CPI", "FOMC"}
            and timedelta_hours(row.event_time, when) <= 24
            and row.event_time >= when
            for row in hits
        ):
            bearing = "cut_size"
            macro = Decimal("0.5")
            minuses = (*minuses, "pre_event_24h")

    n = len(pluses) + len(minuses)
    while n < 5:
        pluses = (*pluses, f"atom_{n}")
        n = len(pluses) + len(minuses)
    if n > 7:
        pluses = pluses[: max(0, 7 - len(minuses))]

    return CardLive(
        symbol=symbol,
        bearing_verdict=bearing,  # type: ignore[arg-type]
        known_at=when,
        macro_multiplier=macro,
        fib_zone=_pick(fib_zone, labels.fib_zone, "none"),  # type: ignore[arg-type]
        fib_level=fib_level if fib_level is not None else labels.fib_level,
        rsi_htf=rsi_htf if rsi_htf is not None else labels.rsi_htf,
        gex_bg=gex_bg if gex_bg is not None else labels.gex_bg,
        fvg_status=_pick(fvg_status, labels.fvg_status, "none"),  # type: ignore[arg-type]
        sweep_status=_pick(sweep_status, labels.sweep_status, "none"),  # type: ignore[arg-type]
        ob_status=ob_status if ob_status is not None else labels.ob_status,
        bos_status=bos_status if bos_status is not None else labels.bos_status,
        market_regime="range" if vol.vah and vol.val else "none",
        volume=vol,
        pluses=tuple(pluses),
        minuses=tuple(minuses),
        venue=venue,  # type: ignore[arg-type]
    )


def _pick(explicit: str | None, computed: str | None, empty: str) -> str:
    if explicit is not None:
        return explicit
    if computed is not None:
        return computed
    return empty


def timedelta_hours(later: datetime, now: datetime) -> float:
    return (later - now).total_seconds() / 3600.0


def _negative(row: NewsRow) -> bool:
    text = f"{row.notes} {row.size_rule} {row.event_class}".lower()
    return any(token in text for token in ("hack", "sec", "ban", "halt", "neg", "other"))
