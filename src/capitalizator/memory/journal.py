"""§5.3 journal columns. Missing value is None, not invented."""

from __future__ import annotations

from typing import Any

JOURNAL_KEYS = (
    "zone_id",
    "touch_ts",
    "trade_px",
    "trade_qty",
    "session_name",
    "session_hour_utc",
    "prior_session_hi",
    "prior_session_lo",
    "poc",
    "vah",
    "val",
    "fib_trend",  # schema only — no algorithm in this release
    "fib_in_05_1",
    "fib_in_ote_gold",
    "rsi_tf",
    "rsi_value",
    "fvg_present",
    "sweep_wick",
    "htf_h4",
    "htf_d1",
    "cav_label",
    "cav_tf",
    "bar_quality",
    "w_now",
    "w_rank",
    "zlg_label",
    "A_same",
    "A_back",
    "A_in",
    "A_opp",
    "tape_eaten",
    "ofi",
    "trades_in_window",
    "wall_state",
    "refill_proxy",
    "prs_tau",
    "prs_y",
    "gex_bg",
    "btc_state",
    "btc_break_against",
    "card_id",
    "bearing_verdict",
    "first_fact",
    "n_cav",
    "n_zlg",
    "jury",
    "shadow_would",
    "shadow_side",
    "shadow_tag",
    "skip_reason",
    "outcome",
    "rho_class_id",
)

KNOWLEDGE_TABLES = (
    "meta",
    "hash_links",
    "episodes",
    "reports",
    "journal_touches",
    "intent_queue",
    "order_queue",
    "overlay",
    "market_event",
    "zone",
    "claim",
    "author_call",
    "news",
    "saved_r",
)


def empty_journal() -> dict[str, Any]:
    return {key: None for key in JOURNAL_KEYS}
