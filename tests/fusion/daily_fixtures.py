"""Complete venue-shaped daily history for entry integration tests."""

from capitalizator.fusion.daily import DAY_SECONDS


def daily_rows(at, low=50, high=150):
    end = at // DAY_SECONDS * DAY_SECONDS
    return [
        [str(int((end - i * DAY_SECONDS) * 1000)), "100", str(high), str(low), "100", "10"]
        for i in range(5, 0, -1)
    ]


def seed_daily(market, at=101, low=50, high=150):
    market.ingest("history", {"tf": "1d", "rows": daily_rows(at, low, high)}, at)
