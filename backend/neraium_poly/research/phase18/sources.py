"""Bounded public external inputs with actual retrieval-time availability."""

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.finance import ORIGIN, digest

MAX_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 2 * 1024**2
SYMBOLS = {"BTCUSDT", "ETHUSDT"}
CRYPTO_TYPES = {"binance_daily_low_barrier", "binance_minute_terminal_close_above"}
OFFICIAL_CALENDARS = {
    "https://www.bls.gov/schedule/news_release/cpi.htm",
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "https://www.bea.gov/news/schedule",
}


def _now():
    return datetime.now(UTC)


def at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_external_time_required")
    return value.astimezone(UTC)


async def _read(client, url, params=None):
    async with client.stream("GET", url, params=params, follow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("external_redirect_forbidden")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError("external_response_byte_limit")
        return bytes(body)


async def collect_event_evidence(contract, *, now, client=None):
    """No keys/account endpoints or source fallback after access/rate rejection.

    ``now`` bounds requested event-time data, never backdates availability. Each
    artifact is available only after the actual final response retrieval.
    """
    c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
    now = at(now)
    if now > _now():
        raise ValueError("future_source_request_cutoff")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers={
        "User-Agent": "Neraium-Poly research (https://github.com/Neraium/Neraium-Poly)"})
    try:
        if c.domain == "crypto":
            if not c.compatible or c.review_required or c.contract_type not in CRYPTO_TYPES:
                raise ValueError("reviewed_crypto_contract_required")
            symbol = c.parameters.get("symbol")
            if symbol not in SYMBOLS:
                raise ValueError("supported_exact_crypto_reference_required")
            end_ms = int(now.timestamp() // 60 * 60000)-1
            if c.contract_type == "binance_daily_low_barrier":
                window = int(at(c.parameters["period_start_utc"]).timestamp()*1000)
                start_ms = min(window, end_ms+1-1000*60000)
            else:
                start_ms = end_ms+1-1000*60000
            if not 0 < end_ms-start_ms <= 2*86400*1000:
                raise ValueError("bounded_crypto_history_window_required")
            responses, total = [], 0
            cursor = start_ms
            for _ in range(2):
                params = {"symbol": symbol, "interval": "1m", "limit": 1000,
                          "startTime": cursor, "endTime": end_ms}
                raw = await _read(client, ORIGIN+"/api/v3/klines", params)
                retrieved = _now()
                total += len(raw)
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("external_total_byte_limit")
                values = json.loads(raw)
                if not isinstance(values, list) or not values:
                    raise ValueError("closed_crypto_candle_array_required")
                responses.append({"url": ORIGIN+"/api/v3/klines", "request": params,
                    "retrieved_at": retrieved.isoformat(), "raw_response_utf8": raw.decode(),
                    "raw_response_sha256": hashlib.sha256(raw).hexdigest()})
                last_close = values[-1][6]
                if type(last_close) is not int or last_close < cursor or last_close > end_ms:
                    raise ValueError("candle_pagination_progress_invalid")
                cursor = last_close+1
                if cursor > end_ms:
                    break
            else:
                raise ValueError("crypto_request_budget_exhausted")
            available = _now()
            payload = {"kind": "binance_complete_closed_minutes", "symbol": symbol,
                "requested_at": now.isoformat(), "start_ms": start_ms, "end_ms": end_ms,
                "responses": responses, "availability_basis": "actual_retrieval_only"}
            evidence = DomainEvidence(id=digest(["phase18-binance", payload, available.isoformat()]),
                timestamp=available, available_at=available, retrieved_at=available,
                source_timestamp=datetime.fromtimestamp(end_ms/1000, UTC), source=ORIGIN,
                domain="crypto", provider="Binance public market data", source_id=f"{symbol}:{start_ms}:{end_ms}",
                content_sha256=digest(payload), payload=payload, independent_of_polymarket=True,
                qualification="qualified_research", missingness=("independent_heldout_calibration", "historical_availability_vintages"))
            completed_minutes(evidence, cutoff=available, symbol=symbol)
            return (evidence,)
        if c.domain == "weather":
            url = c.parameters.get("forecast_url", "")
            if not re.fullmatch(r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d{1,4},\d{1,4}/forecast", url):
                raise ValueError("exact_official_weather_forecast_location_required")
            provider = "NOAA National Weather Service"
            missing = ("matched_station_forecast_residuals", "qualified_predictive_distribution", "resolution_source_compatibility")
        elif c.domain == "economics":
            url = c.parameters.get("source_url", c.parameters.get("calendar_url", ""))
            if url not in OFFICIAL_CALENDARS:
                raise ValueError("exact_official_economic_calendar_required")
            provider = "Official government release calendar"
            missing = ("first_release_vintages", "independent_probability_model", "heldout_calibration")
        else:
            raise ValueError("domain_external_source_unavailable")
        raw = await _read(client, url)
        retrieved = _now()
        payload = {"kind": "official_context_only", "url": url, "raw_response_utf8": raw.decode(),
                   "raw_response_sha256": hashlib.sha256(raw).hexdigest(), "requested_at": now.isoformat()}
        return (DomainEvidence(id=digest(["phase18-context", payload, retrieved.isoformat()]),
            timestamp=retrieved, available_at=retrieved, retrieved_at=retrieved,
            source=f"https://{urlsplit(url).hostname}", domain=c.domain, provider=provider,
            source_id=url, content_sha256=digest(payload), payload=payload,
            independent_of_polymarket=True, qualification="unqualified", missingness=missing),)
    finally:
        if own:
            await client.aclose()


def completed_minutes(evidence, *, cutoff, symbol):
    """Recheck native bytes, exact requests, pagination and source/availability time."""
    e = DomainEvidence.model_validate(evidence.model_dump() if isinstance(evidence, DomainEvidence) else evidence)
    cutoff = at(cutoff)
    if (e.domain != "crypto" or e.source != ORIGIN or e.provider != "Binance public market data"
        or not e.independent_of_polymarket or e.qualification != "qualified_research"
        or max(e.timestamp, e.available_at, e.retrieved_at) > cutoff
        or digest(e.payload) != e.content_sha256 or symbol not in SYMBOLS):
        raise ValueError("qualified_crypto_source_or_cutoff_required")
    payload = e.payload
    if (payload.get("kind") != "binance_complete_closed_minutes" or payload.get("symbol") != symbol
        or payload.get("availability_basis") != "actual_retrieval_only"):
        raise ValueError("crypto_payload_semantics_mismatch")
    start, end = payload.get("start_ms"), payload.get("end_ms")
    if (type(start) is not int or type(end) is not int or start % 60000 or end % 60000 != 59999
        or not 0 < end-start <= 2*86400*1000 or at(payload["requested_at"]) > e.retrieved_at
        or end != int(at(payload["requested_at"]).timestamp() // 60 * 60000)-1):
        raise ValueError("crypto_requested_window_invalid")
    responses = payload.get("responses")
    if not isinstance(responses, list) or not 1 <= len(responses) <= 2:
        raise ValueError("bounded_crypto_source_responses_required")
    result, cursor, total, previous_retrieval = [], start, 0, None
    for item in responses:
        raw = item["raw_response_utf8"].encode(); total += len(raw)
        retrieved = at(item["retrieved_at"])
        if (len(raw) > MAX_BYTES or total > MAX_TOTAL_BYTES or hashlib.sha256(raw).hexdigest() != item["raw_response_sha256"]
            or item.get("url") != ORIGIN+"/api/v3/klines" or retrieved > e.retrieved_at
            or retrieved < at(payload["requested_at"]) or previous_retrieval and retrieved < previous_retrieval):
            raise ValueError("crypto_raw_provenance_or_receipt_invalid")
        previous_retrieval = retrieved
        expected = {"symbol": symbol, "interval": "1m", "limit": 1000, "startTime": cursor, "endTime": end}
        if item.get("request") != expected:
            raise ValueError("crypto_reference_or_pagination_mismatch")
        values = json.loads(raw)
        if not isinstance(values, list) or not 1 <= len(values) <= 1000:
            raise ValueError("bounded_crypto_array_required")
        for row in values:
            if (not isinstance(row, list) or len(row) != 12 or type(row[0]) is not int or type(row[6]) is not int
                or row[0] != cursor or row[6] != row[0]+59999 or row[6] > end
                or row[6] >= int(cutoff.timestamp()*1000)):
                raise ValueError("crypto_closed_contiguous_minute_required")
            prices = [float(row[i]) for i in (1, 2, 3, 4)]
            if (any(isinstance(row[i], bool) for i in (1, 2, 3, 4)) or any(not math.isfinite(v) or v <= 0 for v in prices)
                or not prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1]):
                raise ValueError("crypto_ohlc_invalid")
            result.append({"open_ms": row[0], "close_ms": row[6], "open": prices[0],
                           "high": prices[1], "low": prices[2], "close": prices[3]})
            cursor = row[6]+1
    if cursor != end+1 or len(result) > 2880:
        raise ValueError("crypto_window_incomplete")
    if not 0 < cutoff.timestamp()*1000-result[-1]["close_ms"] <= 120000:
        raise ValueError("crypto_closed_reference_stale")
    return result
