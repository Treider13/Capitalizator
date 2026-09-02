"""Evening map: touches / gestures / gaps. No лонг / купи / завтра."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalizator.memory.registry import Touch
from capitalizator.ops.daily_map_report import GapRow, daily_map_report, skip_line
from capitalizator.zones.model import Zone

DAY = "2026-08-30"
CREATED = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
PRINT = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
ZONE = Zone.create(
    symbol="ETHUSDT",
    tf="1d",
    side="support",
    lo=Decimal("3240"),
    hi=Decimal("3260"),
    method="prior_day_hl",
    created_as_of=CREATED,
)


def _touch(*, eaten: bool = False, gesture: str = "DEFEND") -> Touch:
    return Touch(
        touch_id="t1",
        zone_id=ZONE.zone_id,
        ts=PRINT,
        trade_px=Decimal("3245"),
        trade_qty=Decimal("1"),
        outcome="bounce",
        tape_eaten=eaten,
        gesture=gesture,
    )


def test_report_has_touches_gesture_gaps_no_advice() -> None:
    text = daily_map_report(
        day=DAY,
        rows=[(ZONE, _touch(eaten=True))],
        gaps=[GapRow(symbol="ETHUSDT", stream="trades", n=1)],
        ping_ms=18.0,
    )
    assert "ETHUSDT 3240–3260" in text
    assert "1 касание" in text
    assert "eaten 1" in text
    assert "DEFEND" in text
    assert "Дыры: 1" in text
    assert "18.0 мс" in text
    for word in ("лонг", "шорт", "купи", "продай", "завтра"):
        assert word not in text.lower()


def test_two_runs_same_text() -> None:
    args = dict(
        day=DAY,
        rows=[(ZONE, _touch())],
        gaps=(),
        ping_ms=None,
    )
    assert daily_map_report(**args) == daily_map_report(**args)


def test_advice_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="advise"):
        daily_map_report(day="купи BTC", rows=[])


def test_skip_line_counts_no_tvh() -> None:
    text = skip_line(
        [
            _touch(),
            Touch(
                touch_id="t2",
                zone_id=ZONE.zone_id,
                ts=PRINT,
                trade_px=Decimal("3245"),
                trade_qty=Decimal("1"),
                outcome="pending",
                skip_reason="no_tvh",
            ),
        ]
    )
    assert text == "Пропуски: без ТВХ 1."
    report = daily_map_report(
        day=DAY,
        rows=[
            (
                ZONE,
                Touch(
                    touch_id="t3",
                    zone_id=ZONE.zone_id,
                    ts=PRINT,
                    trade_px=Decimal("3245"),
                    trade_qty=Decimal("1"),
                    outcome="pending",
                    skip_reason="no_tvh",
                ),
            )
        ],
    )
    assert "без ТВХ 1" in report
    for word in ("лонг", "шорт", "купи", "продай", "завтра"):
        assert word not in report.lower()
