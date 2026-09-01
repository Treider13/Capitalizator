"""Build a 5–7 atom CardLive. At least one minus. Does not send. No Telegram."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from capitalizator.card.live import CardLive, VolumeSnapshot
from capitalizator.news_macro.ingest import NewsRow
from capitalizator.types import require_utc

IMMINENT_HOURS = 2


def from_news(
    *,
    symbol: str,
    now: datetime,
    calendar: tuple[NewsRow, ...],
    volume: VolumeSnapshot | None = None,
    fib_zone: str = "OTE",
    fib_level: str | None = "0.718",
    rsi_htf: str | None = "52",
    gex_bg: str | None = "+2.1M",
    fvg_status: str = "filled",
    sweep_status: str = "done",
    venue: str = "perp",
) -> CardLive:
    when = require_utc(now)
    vol = volume or VolumeSnapshot()
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
        for row in hits
        if row.event_class == "LISTING" and symbol not in row.assets
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
    elif listing and symbol not in {a for row in listing for a in row.assets}:
        bearing = "hold"
        pluses = ("listing_seen",)
        minuses = ("not_in_universe",)
        venue = "spot_proposal"
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
        fib_zone=fib_zone,  # type: ignore[arg-type]
        fib_level=fib_level,
        rsi_htf=rsi_htf,
        gex_bg=gex_bg,
        fvg_status=fvg_status,  # type: ignore[arg-type]
        sweep_status=sweep_status,  # type: ignore[arg-type]
        market_regime="range" if vol.vah and vol.val else "none",
        volume=vol,
        pluses=tuple(pluses),
        minuses=tuple(minuses),
        venue=venue,  # type: ignore[arg-type]
    )


def timedelta_hours(later: datetime, now: datetime) -> float:
    return (later - now).total_seconds() / 3600.0


def _negative(row: NewsRow) -> bool:
    text = f"{row.notes} {row.size_rule} {row.event_class}".lower()
    return any(token in text for token in ("hack", "sec", "ban", "halt", "neg", "other"))
