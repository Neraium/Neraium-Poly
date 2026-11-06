"""Controlled financial fixtures, never authentic price or performance claims."""
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14 import finance
from neraium_poly.research.phase14.contracts import DomainEvidence

NOW = datetime(2026, 11, 6, 9, tzinfo=UTC)
RULES = ('This market will resolve to "Yes" if the Binance 1 minute candle for BTC/USDT closing at 12:00 in the ET timezone (noon) on the date specified in the title has a final "Close" price higher than the price specified in the title. Otherwise, this market will resolve to "No".\n\n'
'The resolution source for this market is Binance, specifically the BTC/USDT "Close" prices currently available at https://www.binance.com/en/trade/BTC_USDT with "1m" and "Candles" selected on the top bar.\n\n'
'Please note that this market is about the price according to Binance BTC/USDT, not according to other exchanges or trading pairs.\n\n'
'Price precision is determined by the number of decimal places in the source.')


def market():
    return MarketSnapshot(id="CONTROLLED", timestamp=NOW, available_at=NOW, source="CONTROLLED",
        market_id="fixture", event_id="fixture-event", token_id="t", question="Will the price of Bitcoin be above $78,000 on November 6?",
        outcome="Yes", probability=.5, status="active", resolution_rules=RULES,
        resolution_source="https://www.binance.com/en/trade/BTC_USDT", end_time=NOW.replace(hour=17))


def raw_candles(n=1000):
    end = int(NOW.timestamp()*1000)
    values = []
    for i in range(n):
        t = end-(n-i)*60000
        close = 75000*math.exp(.001*math.sin(i))
        values.append([t, str(close), str(close+1), str(close-1), str(close), "2", t+59999, "3", 5, "1", "2", "0"])
    return values


def evidence(rows=None):
    body = json.dumps(raw_candles() if rows is None else rows)
    payload = {"source_url": finance.ORIGIN+"/api/v3/klines", "request": {"symbol": "BTCUSDT", "interval": "1m", "limit": 1000},
               "raw_response_utf8": body, "raw_response_sha256": hashlib.sha256(body.encode()).hexdigest()}
    return DomainEvidence(id="fixture-data", timestamp=NOW, available_at=NOW, source=finance.ORIGIN,
        domain="crypto", provider="Binance public market data", source_id="fixture", retrieved_at=NOW,
        content_sha256=finance.digest(payload), payload=payload, independent_of_polymarket=True, qualification="qualified_research")


def reviewed_contract():
    c = finance.map_financial(market(), now=NOW)
    # Controlled review fixture only. Actual ambiguous market mappings stay blocked.
    return c.model_copy(update={"review_required": False, "parameters": {**c.parameters, "candle_convention": "reviewed_minute_ending_boundary"}})


def test_exact_noon_contract_maps_but_candle_convention_is_not_silently_approved():
    c = finance.map_financial(market(), now=NOW)
    assert c.compatible and c.review_required
    assert c.parameters["resolution_boundary"] == "2026-11-06T17:00:00+00:00"
    assert c.parameters["candidate_candle_close"].endswith("16:59:59.999000+00:00")
    assert finance.forecast_financial(c, [evidence()], cutoff=NOW)["probability"] is None


@pytest.mark.parametrize("change", [{"resolution_source":"https://coinbase.com"}, {"resolution_rules": RULES.replace('higher than','equal to or higher than')},
                                   {"question":"Will Bitcoin dip to $75,000 in November?"}, {"end_time": NOW.replace(hour=18)}])
def test_wrong_exchange_barrier_operator_and_time_cannot_use_terminal_model(change):
    c = finance.map_financial(market().model_copy(update=change), now=NOW)
    assert not c.compatible


def test_closed_candles_ignore_open_future_rows_and_keep_causal_replay():
    rows = raw_candles(999)
    future = [int(NOW.timestamp()*1000),"1","999999",".1","999999","2",int(NOW.timestamp()*1000)+59999,"3",4,"1","2","0"]
    assert len(finance.closed_candles(evidence(rows+[future]), cutoff=NOW, symbol="BTCUSDT")) == 999


@pytest.mark.parametrize("kind", ["gap", "duplicate", "bad_ohlc", "stale", "wrong_symbol", "future_availability", "tamper"])
def test_financial_source_failure_modes_fail_closed(kind):
    rows = raw_candles()
    if kind == "gap": rows.pop(500)
    elif kind == "duplicate": rows[-1] = rows[-2]
    elif kind == "bad_ohlc": rows[-1][2] = "1"
    elif kind == "stale": rows = rows[:-3]
    e = evidence(rows)
    if kind == "wrong_symbol": e = e.model_copy(update={"payload": {**e.payload,"request":{"symbol":"ETHUSDT","interval":"1m","limit":1000}}})
    elif kind == "future_availability": e = e.model_copy(update={"available_at": NOW+timedelta(seconds=1)})
    elif kind == "tamper": e = e.model_copy(update={"content_sha256":"f"*64})
    with pytest.raises(ValueError): finance.closed_candles(e, cutoff=NOW, symbol="BTCUSDT")


def test_reviewed_model_is_reproducible_threshold_probability_not_market_price_feature():
    c, e = reviewed_contract(), evidence()
    first = finance.forecast_financial(c, [e], cutoff=NOW)
    assert first == finance.forecast_financial(c, [e], cutoff=NOW)
    assert 0 <= first["probability"] <= 1 and first["training_observations"] == 1000
    assert first["uncertainty"]["lower_probability"] == 0 and first["uncertainty"]["upper_probability"] == 1
    assert first["trading_authority"] is False and first["brier"] is None
    other = c.model_copy(update={"parameters": {**c.parameters,"selected_outcome":"No"}})
    assert finance.forecast_financial(other,[e],cutoff=NOW)["probability"] == pytest.approx(1-first["probability"])


async def test_collector_only_unauthenticated_get_and_original_bytes():
    raw = json.dumps(raw_candles()).encode()
    def handler(request):
        assert request.method == "GET" and request.url.host == "data-api.binance.vision"
        assert not request.headers.get("X-MBX-APIKEY")
        return httpx.Response(200,content=raw)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        (e,) = await finance.collect_financial(finance.map_financial(market(),now=NOW),client=client,clock=lambda:NOW)
    assert e.payload["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert e.available_at == NOW and e.source_timestamp is None


async def test_geographic_rejection_is_not_retried_through_another_origin():
    calls=[]
    def handler(request): calls.append(str(request.url));return httpx.Response(451)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await finance.collect_financial(finance.map_financial(market(),now=NOW),client=client,clock=lambda:NOW)
    assert len(calls)==1
