"""Controlled public-source contracts; fixtures never count as genuine observations."""

import hashlib
import itertools
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.research.phase18.forecasting import daily_low_rules
from neraium_poly.research.phase19 import discovery

NOW = datetime(2026, 11, 7, 7, tzinfo=UTC)


def native(asset="bitcoin"):
    name = "Bitcoin" if asset == "bitcoin" else "Ethereum"
    symbol, threshold = ("BTC", "75,000") if asset == "bitcoin" else ("ETH", "2,200")
    return {"id": asset+"-CONTROLLED-market", "question": f"Will {name} dip to ${threshold} on November 7?",
        "clobTokenIds": json.dumps([asset+"-yes", asset+"-no"]), "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.4","0.6"]', "active": True, "closed": False,
        "acceptingOrders": True, "enableOrderBook": True, "liquidity": "1000", "volume24hr": 100,
        "endDate": "2026-11-08T05:00:00Z", "description": daily_low_rules(name),
        "resolutionSource": f"https://www.binance.com/en/trade/{symbol}_USDT"}


def event(asset="bitcoin"):
    return {"id": asset+"-CONTROLLED-parent", "slug": f"what-price-will-{asset}-hit-on-november-7-2026", "markets": [native(asset)]}


def book(token, *, age=2):
    return {"asset_id": token, "timestamp": str(int((NOW-timedelta(seconds=age)).timestamp()*1000)),
        "bids": [{"price": ".4", "size": "100"}], "asks": [{"price": ".41", "size": "200"}]}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    ticks = itertools.count(step=.5)
    monkeypatch.setattr(discovery, "_now", lambda: NOW)
    monkeypatch.setattr(discovery, "monotonic", lambda: next(ticks))


async def run(handler, **kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await discovery.discover_forecast_markets(now=NOW, client=client, **kwargs)


def valid_handler(request):
    if request.method == "GET":
        return httpx.Response(200, json=[event("bitcoin" if "bitcoin" in request.url.params["slug"] else "ethereum")])
    assert request.method == "POST" and str(request.url) == "https://clob.polymarket.com/books"
    return httpx.Response(200, json=[book(row["token_id"]) for row in json.loads(request.content)])


async def test_exact_year_current_day_and_native_executable_preflight():
    calls = []
    def handler(request):calls.append(request);return valid_handler(request)
    r = await run(handler)
    assert r["requests_used"] == 3 and len(calls) == 3 and len(r["markets"]) == 2
    assert len(r["books"]) == 4 and all(h["preflight_eligible"] for h in r["health_by_market"].values())
    assert all(r.url.params["slug"].endswith("november-7-2026") for r in calls[:2])
    assert all(h["trading_authority"] is False for h in r["health_by_market"].values())
    assert not r["trading_authority"] and not r["certification_authority"]
    for p in r["provenance"]:
        assert hashlib.sha256(p["raw_response_utf8"].encode()).hexdigest() == p["raw_sha256"]
        assert p["retrieved_at"] == p["available_at"] == NOW.isoformat()


async def test_source_receipt_never_backdated_to_request_cutoff(monkeypatch):
    monkeypatch.setattr(discovery, "_now", lambda: NOW+timedelta(seconds=1))
    r = await run(valid_handler)
    assert r["requested_at"] == NOW.isoformat()
    assert all(p["available_at"] == (NOW+timedelta(seconds=1)).isoformat() for p in r["provenance"])


async def test_stale_one_sided_books_are_only_warmup_not_eligible():
    def handler(request):
        if request.method == "GET":return valid_handler(request)
        values = [book(row["token_id"], age=60) for row in json.loads(request.content)]
        values[0]["asks"] = []
        return httpx.Response(200, json=values)
    r = await run(handler)
    assert len(r["markets"]) == 2
    assert all(not x["preflight_eligible"] and x["status"] == "metadata_only_warmup" for x in r["health_by_market"].values())
    assert any("missing_liquidity" in x["rejections"] for x in r["health_by_market"].values())
    assert all("stale_book" in x["rejections"] for x in r["health_by_market"].values())


async def test_fresh_valid_book_candidates_rank_before_stale_liquidity():
    def handler(request):
        if request.method == "GET":
            asset = "bitcoin" if "bitcoin" in request.url.params["slug"] else "ethereum"
            e = event(asset);e["markets"][0]["liquidity"] = "9999999" if asset == "ethereum" else "1"
            return httpx.Response(200, json=[e])
        return httpx.Response(200, json=[book(x["token_id"], age=60 if "ethereum" in x["token_id"] else 2) for x in json.loads(request.content)])
    r = await run(handler)
    assert r["markets"][0]["id"].startswith("bitcoin")
    assert r["health_by_market"][r["markets"][1]["id"]]["preflight_eligible"] is False


@pytest.mark.parametrize("mutation", ["parent", "rules", "closed", "oldyear", "ambiguous_time", "tokens"])
async def test_identity_rules_lifecycle_and_binary_mapping_fail_closed(mutation):
    def handler(request):
        if request.method == "POST":raise AssertionError("incompatible metadata must not request books")
        asset = "bitcoin" if "bitcoin" in request.url.params["slug"] else "ethereum";e = event(asset);m = e["markets"][0]
        if mutation == "parent":m["eventId"] = "CONTROLLED wrong-parent"
        if mutation == "rules":m["description"] += "CONTROLLED changed settlement rule"
        if mutation == "closed":m["closed"] = True
        if mutation == "oldyear":m["endDate"] = "2025-11-08T05:00:00Z"
        if mutation == "ambiguous_time":m["endDate"] = "2026-11-08T06:00:00Z"
        if mutation == "tokens":m["clobTokenIds"] = '["only-one"]'
        return httpx.Response(200, json=[e])
    r = await run(handler)
    assert not r["markets"] and not r["books"] and r["rejections"]


async def test_access_or_rate_rejection_does_not_fallback_or_retry():
    calls = []
    def handler(request):calls.append(request);return httpx.Response(429, json={"error": "CONTROLLED throttled"})
    r = await run(handler)
    assert len(calls) == 1 and r["requests_used"] == 1 and not r["markets"]
    assert r["provenance"][0]["http_status"] == 429 and r["rejections"]


async def test_request_and_candidate_budgets_and_no_false_book_eligibility():
    r = await run(valid_handler, max_requests=1, max_candidates=1)
    assert r["requests_used"] == 1 and len(r["markets"]) == 1 and not r["books"]
    assert all(not x["preflight_eligible"] for x in r["health_by_market"].values())
    assert r["rejections"]["book_preflight_request_budget_exhausted"] == 1


async def test_duplicate_book_and_unknown_token_not_double_counted():
    def handler(request):
        if request.method == "GET":return valid_handler(request)
        values = [book(x["token_id"]) for x in json.loads(request.content)]
        return httpx.Response(200, json=values+[deepcopy(values[0]), book("CONTROLLED unknown")])
    r = await run(handler)
    assert len(r["books"]) == 3
    assert r["rejections"]["duplicate_book_token"] == r["rejections"]["book_token_not_in_discovered_event"] == 1


async def test_response_size_and_input_limits_fail_closed(monkeypatch):
    monkeypatch.setattr(discovery, "MAX_RESPONSE_BYTES", 32)
    r = await run(lambda _r: httpx.Response(200, content=b"x"*33))
    assert not r["markets"] and r["requests_used"] == 1 and r["rejections"]
    for kw in ({"max_requests": 7}, {"max_candidates": 41}, {"max_requests": True}):
        with pytest.raises(ValueError):await run(valid_handler, **kw)
    with pytest.raises(ValueError):await discovery.discover_forecast_markets(now=NOW.replace(tzinfo=None))
