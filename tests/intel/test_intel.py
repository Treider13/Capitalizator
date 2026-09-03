"""Contour B fetchers, strict LLM extraction, resolution on our own tape — no sockets."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from capitalizator.intel import fetchers
from capitalizator.intel.llm import BudgetExceeded, LLMClient, parse_extraction
from capitalizator.intel.run import cycle
from capitalizator.ops.knowledge import open_knowledge
from capitalizator.ops.settings import Settings, add_source
from capitalizator.ops.vault import init_vault

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

RSS = """<rss><channel><item><title>SEC sues exchange X over unregistered securities</title>
<link>https://example.com/a</link></item><item><title>Bitcoin ETF inflows hit record</title>
<link>https://example.com/b</link></item></channel></rss>"""

REDDIT = {"data": {"children": [
    {"data": {"id": "abc", "author": "u1", "title": "BTC to 100k this week", "selftext": "long it", "created_utc": 1788400000, "permalink": "/r/x/abc", "score": 10, "num_comments": 2}},
]}}

X_USER = {"data": {"id": "42", "username": "trader"}}
X_TWEETS = {"data": [{"id": "1", "text": "SOL short to 100, 1d. join via my ref link", "created_at": "2026-09-03T11:00:00Z",
                      "entities": {"urls": [{"expanded_url": "https://ex.com/?r=abc"}]}, "public_metrics": {"like_count": 5}}]}
HL = {"assetPositions": [{"position": {"coin": "BTC", "szi": "-2.5", "entryPx": "65000", "leverage": {"value": 5}, "unrealizedPnl": "10"}}],
      "marginSummary": {"accountValue": "100000"}}
BYBIT = {
    "account-ratio": {"retCode": 0, "result": {"list": [{"buyRatio": "0.6", "sellRatio": "0.4"}]}},
    "open-interest": {"retCode": 0, "result": {"list": [{"openInterest": "12345"}]}},
    "funding/history": {"retCode": 0, "result": {"list": [{"fundingRate": "0.0001", "fundingRateTimestamp": "1"}]}},
}
FNG = {"data": [{"value": "72", "value_classification": "Greed", "timestamp": "1788400000"}]}


def fake_get(url: str, headers: dict) -> bytes:
    if "example.org/feed" in url:
        return RSS.encode()
    if "reddit.com" in url:
        return json.dumps(REDDIT).encode()
    if "api.x.com/2/users/by" in url:
        return json.dumps(X_USER).encode()
    if "api.x.com/2/users/42/tweets" in url:
        return json.dumps(X_TWEETS).encode()
    for key, body in BYBIT.items():
        if key in url:
            return json.dumps(body).encode()
    if "alternative.me" in url:
        return json.dumps(FNG).encode()
    raise AssertionError(f"unexpected url {url}")


def fake_post(url: str, body: bytes, headers: dict) -> bytes:
    if "hyperliquid" in url:
        return json.dumps(HL).encode()
    raise AssertionError(url)


def test_fetchers_carry_known_at_and_refuse_forbidden_urls() -> None:
    rss = fetchers.fetch_rss("https://example.org/feed", now=NOW, get=fake_get)
    assert len(rss) == 2 and rss[0].known_at == NOW and rss[0].extra["event_class"]
    with pytest.raises(ValueError):
        fetchers.fetch_rss("https://t.me/s/channel", now=NOW, get=fake_get)
    with pytest.raises(ValueError):
        fetchers.fetch_rss("http://example.org/feed", now=NOW, get=fake_get)
    rd = fetchers.fetch_reddit("CryptoCurrency", now=NOW, get=fake_get)
    assert rd[0].author_id == "reddit:u1" and "BTC to 100k" in rd[0].text
    with pytest.raises(ValueError, match="bearer"):
        fetchers.fetch_x_account("trader", bearer="", now=NOW, get=fake_get)
    tw = fetchers.fetch_x_account("@trader", bearer="B", now=NOW, get=fake_get)
    assert tw[0].extra["has_ref_link"] is True and tw[0].author_id == "x:trader"
    hl = fetchers.fetch_hl_wallet("0x" + "1" * 40, now=NOW, post=fake_post)
    assert hl.extra["positions"][0]["coin"] == "BTC"
    assert fetchers.hl_cohort_exposure([hl, hl])["BTC"]["net_size"] == "-5.000000"
    bb = fetchers.fetch_bybit_public("BTCUSDT", now=NOW, get=fake_get)
    assert bb.extra["buy_ratio"] == "0.6" and bb.extra["open_interest"] == "12345"
    assert fetchers.fetch_fng(now=NOW, get=fake_get).extra["value"] == "72"


def test_extraction_is_strict_and_never_carries_advice() -> None:
    good = '{"claims":[{"asset":"sol","side":"short","target":"100","horizon":"1d","confidence":0.7},' \
           '{"asset":"???","side":"long"}],"motive":{"promo":true,"ref_link":true},"event_class":"none","trade_advice":true}'
    claims, promo, ref, ev = parse_extraction("blah " + good + " tail")
    assert len(claims) == 1 and claims[0].asset == "SOLUSDT" and claims[0].horizon == "1d"
    assert promo and ref and ev == "none"
    assert parse_extraction("no json here") is None
    bad_h = '{"claims":[{"asset":"BTCUSDT","side":"long","horizon":"soon","confidence":2}]}'
    c, *_ = parse_extraction(bad_h)
    assert c[0].horizon is None and c[0].confidence == 1.0


def test_llm_client_meters_budget_and_parses_provider_replies(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    calls: list[str] = []

    def post(url: str, body: bytes, headers: dict) -> bytes:
        calls.append(url)
        assert "x-api-key" in headers and headers["x-api-key"] == "sk-test"
        return json.dumps({"content": [{"type": "text", "text": '{"claims":[{"asset":"BTCUSDT","side":"long","horizon":"4h","confidence":0.6}],"motive":{},"event_class":"none"}'}],
                           "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}).encode()

    llm = LLMClient(provider="anthropic", model="m", api_key="sk-test", monthly_budget_usd=5.0, knowledge=kn, post=post, clock=lambda: NOW)
    ext = llm.extract("BTC looks strong")
    assert ext is not None and ext.claims[0].asset == "BTCUSDT" and ext.cost_usd == pytest.approx(3.0)
    assert llm.spent() == pytest.approx(3.0)
    llm.extract("again")  # 6.0 > 5.0 budget after this
    with pytest.raises(BudgetExceeded):
        llm.extract("third")
    assert len(calls) == 2
    kn.close()


def test_cycle_stores_items_extracts_claims_and_resolves_on_our_prices(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "v")
    kn = open_knowledge(vault)
    Settings(vault).update({"x.bearer": "B"}, ack=True)
    # replace defaults with fixture sources
    from capitalizator.ops.settings import save_sources
    save_sources(kn, [])
    add_source(kn, kind="rss", value="https://example.org/feed", ack=True)
    add_source(kn, kind="reddit", value="CryptoCurrency", ack=True)
    add_source(kn, kind="x_account", value="trader", ack=True)
    add_source(kn, kind="hl_wallet", value="0x" + "1" * 40, ack=True)
    add_source(kn, kind="rss", value="https://dead.example.net/x", ack=True)  # will error

    def post(url: str, body: bytes, headers: dict) -> bytes:
        if "hyperliquid" in url:
            return fake_post(url, body, headers)
        text = json.loads(body.decode())["messages"][0]["content"]
        side = "short" if "SOL short" in text else ("long" if "BTC to 100k" in text else "none")
        asset = "SOLUSDT" if side == "short" else "BTCUSDT"
        return json.dumps({"content": [{"type": "text", "text": json.dumps({"claims": [] if side == "none" else [
            {"asset": asset, "side": side, "horizon": "4h", "confidence": 0.8}], "motive": {}, "event_class": "none"})}],
            "usage": {"input_tokens": 10, "output_tokens": 10}}).encode()

    llm = LLMClient(provider="anthropic", model="m", api_key="k", monthly_budget_usd=10, knowledge=kn, post=post, clock=lambda: NOW)
    kn.put_last_price("BTCUSDT", "65000")
    kn.put_last_price("SOLUSDT", "150")
    out = cycle(vault, kn, now=NOW, get=fake_get, post=post, llm=llm)
    assert out["fetch"]["stored"] >= 4 and out["extract"]["calls"] == 2
    srcs = {s["value"]: s for s in json.loads(kn.meta("intel_sources"))}
    assert srcs["https://example.org/feed"]["last_ok"] and srcs["https://dead.example.net/x"]["last_error"]
    assert json.loads(kn.meta("sentiment"))["value"] == "72"
    assert json.loads(kn.meta("hl_cohort"))["exposure"]["BTC"]["net_size"] == "-2.500000"
    assert json.loads(kn.meta("bybit_public:BTCUSDT"))["buy_ratio"] == "0.6"
    calls = [c for c in kn.author_calls() if c.get("horizon")]
    assert {c["asset"] for c in calls} == {"BTCUSDT", "SOLUSDT"}
    assert all(c.get("ref_px") for c in calls)  # reference price = our price at first sighting
    # 4h later SOL fell 2% → the short is a hit; BTC flat → miss
    kn.put_last_price("SOLUSDT", "147")
    later = NOW + timedelta(hours=5)
    out2 = cycle(vault, kn, now=later, get=fake_get, post=post, llm=llm)
    assert out2["resolve"]["resolved"] == 2
    by_asset = {c["asset"]: c for c in kn.author_calls() if c.get("horizon")}
    assert by_asset["SOLUSDT"]["hit"] is True and by_asset["BTCUSDT"]["hit"] is False
    weights = json.loads(kn.meta("author_weights"))["authors"]
    assert weights["x:trader"]["n"] == 1 and Decimal(weights["x:trader"]["weight"]) == 0  # n<5 → 0
    kn.close()
