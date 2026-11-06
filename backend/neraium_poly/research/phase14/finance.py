"""Read-only crypto evidence and conservative terminal-threshold research.

An exact market reference is mandatory. No account endpoint, wallet, exchange
fallback, barrier-to-terminal substitution or production model authority exists.
"""
import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import stdev
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence

ORIGIN = "https://data-api.binance.vision"
MODEL_VERSION = "binance-terminal-logdiffusion-research-v1"
FEATURE_VERSION = "closed-contiguous-1m-logreturns-v1"
MAX_BYTES = 512 * 1024
ASSETS = {"Bitcoin": ("BTC", "BTCUSDT"), "Ethereum": ("ETH", "ETHUSDT")}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def map_financial(market, *, now):
    """Recognize audited Binance noon-close template, quarantining time convention.

    Binance chart candles have opening labels and separate close timestamps. The
    exchange's minute-ending boundary cannot silently be assumed to be the same
    minute intended by a market's human-readable 'closing at noon' wording.
    """
    m = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    if now.tzinfo is None or m.timestamp > now or m.available_at > now or m.status != "active":
        raise ValueError("financial_noncausal_or_inactive_market")
    match = re.fullmatch(r"Will the price of (Bitcoin|Ethereum) be above \$([\d,]+) on ([A-Z][a-z]+ \d{1,2})\?", m.question)
    params, reasons = {}, []
    compatible = False
    kind = "unsupported_financial_contract"
    if match and m.end_time is not None:
        if m.end_time.tzinfo is None:
            raise ValueError("financial_aware_settlement_time_required")
        name, threshold, date = match.groups()
        asset, symbol = ASSETS[name]
        source = f"https://www.binance.com/en/trade/{asset}_USDT"
        expected = (
            f'This market will resolve to "Yes" if the Binance 1 minute candle for {asset}/USDT closing at 12:00 in the ET timezone (noon) on the date specified in the title has a final "Close" price higher than the price specified in the title. Otherwise, this market will resolve to "No".\n\n'
            f'The resolution source for this market is Binance, specifically the {asset}/USDT "Close" prices currently available at {source} with "1m" and "Candles" selected on the top bar.\n\n'
            f'Please note that this market is about the price according to Binance {asset}/USDT, not according to other exchanges or trading pairs.\n\n'
            'Price precision is determined by the number of decimal places in the source.'
        )
        local = m.end_time.astimezone(ZoneInfo("America/New_York"))
        expected_date = datetime.strptime(f"{local.year} {date} 12:00", "%Y %B %d %H:%M").replace(tzinfo=ZoneInfo("America/New_York"))
        if m.resolution_source != source or m.resolution_rules != expected or expected_date != local:
            reasons.append("financial_exact_rule_reference_or_time_mismatch")
        elif m.outcome not in {"Yes", "No"} or m.end_time <= now or float(threshold.replace(",", "")) <= 0:
            reasons.append("financial_unsupported_outcome_or_past_target")
        else:
            compatible = True
            kind = "binance_minute_terminal_close_above"
            params = {"asset": asset, "symbol": symbol, "quote_currency": "USDT", "price_definition": "final_close",
                      "threshold": float(threshold.replace(",", "")), "operator": ">", "selected_outcome": m.outcome,
                      "timezone": "America/New_York", "resolution_boundary": m.end_time.isoformat(),
                      "candidate_candle_open": (m.end_time-timedelta(minutes=1)).isoformat(),
                      "candidate_candle_close": (m.end_time-timedelta(milliseconds=1)).isoformat(),
                      "candle_convention": "unreviewed_minute_ending_boundary", "reference_source": source}
            reasons.append("explicit_candle_label_vs_close_time_review_required")
    else:
        reasons.append("barrier_path_or_non_binance_terminal_contract_not_supported")
    return DomainContract(id=digest([m.id, "financial-contract-v1"]), timestamp=now, available_at=now,
        source="neraium-poly/financial-contract/v1", domain="crypto" if "binance.com" in m.resolution_source else "finance",
        event_id=m.event_id, market_id=m.market_id, token_id=m.token_id, contract_type=kind,
        probability_semantics="binary_event_probability" if compatible else "unsupported",
        rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(), parameters=params,
        compatible=compatible, review_required=True, reasons=tuple(reasons))


async def _read(client, url, params=None):
    async with client.stream("GET", url, params=params, follow_redirects=False) as response:
        response.raise_for_status()  # No fallback on geographic/rate/access rejection.
        if response.is_redirect or int(response.headers.get("content-length", "0")) > MAX_BYTES:
            raise ValueError("financial_source_redirect_or_size")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError("financial_source_size")
        return bytes(body)


async def collect_financial(contract, *, client=None, clock=None):
    """One unauthenticated market-data-only GET; caller owns durable evidence budget."""
    c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
    if not c.compatible or c.contract_type != "binance_minute_terminal_close_above" or c.parameters.get("symbol") not in {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("financial_supported_reference_required")
    clock = clock or (lambda: datetime.now(UTC))
    requested = clock()
    params = {"symbol": c.parameters["symbol"], "interval": "1m", "limit": 1000,
              "endTime": int(requested.timestamp() // 60 * 60000)-1}
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers={"User-Agent": "Neraium-Poly public research/0.1"})
    try:
        raw = await _read(client, ORIGIN + "/api/v3/klines", params)
        at = clock()
        payload = {"source_url": ORIGIN + "/api/v3/klines", "request": params,
                   "raw_response_utf8": raw.decode("utf-8"), "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
                   "availability": "Actual retrieval; no historical publication claim"}
        evidence = DomainEvidence(id=digest(["binance-klines", payload, at.isoformat()]), timestamp=at,
            available_at=at, source=ORIGIN, domain="crypto", provider="Binance public market data",
            source_id=f"{params['symbol']}:1m:{params['endTime']}", retrieved_at=at,
            content_sha256=digest(payload), payload=payload, independent_of_polymarket=True,
            qualification="qualified_research", missingness=("historical_availability_vintages", "heldout_calibration"))
        closed_candles(evidence, cutoff=at, symbol=params["symbol"])
        return (evidence,)
    finally:
        if own:
            await client.aclose()


def closed_candles(evidence, *, cutoff, symbol):
    e = DomainEvidence.model_validate(evidence.model_dump() if isinstance(evidence, DomainEvidence) else evidence)
    if (cutoff.tzinfo is None or e.available_at > cutoff or e.retrieved_at > cutoff or e.timestamp > cutoff
        or e.source != ORIGIN or e.provider != "Binance public market data" or not e.independent_of_polymarket
        or e.qualification != "qualified_research" or digest(e.payload) != e.content_sha256):
        raise ValueError("financial_source_provenance_or_availability")
    payload = e.payload
    raw = payload["raw_response_utf8"].encode()
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != payload["raw_response_sha256"]:
        raise ValueError("financial_raw_hash_or_size")
    request = payload["request"]
    if (payload.get("source_url") != ORIGIN + "/api/v3/klines" or request.get("symbol") != symbol
        or request.get("interval") != "1m" or request.get("limit") != 1000):
        raise ValueError("financial_reference_or_interval_mismatch")
    values = json.loads(raw)
    if not isinstance(values, list) or not 2 <= len(values) <= 1000:
        raise ValueError("financial_bounded_candle_array_required")
    result, seen = [], set()
    for row in values:
        if not isinstance(row, list) or len(row) != 12:
            raise ValueError("financial_candle_schema")
        opened, closed = row[0], row[6]
        if type(opened) is not int or type(closed) is not int or opened % 60000 or closed != opened + 59999:
            raise ValueError("financial_minute_timestamp_schema")
        if opened in seen:
            raise ValueError("financial_duplicate_candle")
        seen.add(opened)
        # No forming candle (or later data) is a completed training observation.
        if closed >= int(cutoff.timestamp()*1000):
            continue
        prices = [float(row[i]) for i in (1, 2, 3, 4)]
        if any(not math.isfinite(x) or x <= 0 for x in prices) or not prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1]:
            raise ValueError("financial_invalid_ohlc")
        result.append((opened, closed, prices[3]))
    result.sort()
    if any(right[0]-left[0] != 60000 for left, right in pairwise(result)):
        raise ValueError("financial_data_gap")
    if not result or cutoff.timestamp()*1000 - result[-1][1] > 120000:
        raise ValueError("financial_stale_completed_candle")
    return result


def forecast_financial(contract, evidence, *, cutoff):
    """Explicitly reviewed terminal-close estimate, never barrier-crossing probability."""
    c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
    if (not c.compatible or c.contract_type != "binance_minute_terminal_close_above"
        or c.probability_semantics != "binary_event_probability"):
        return {"status": "withheld", "reasons": ["unsupported_financial_contract"], "probability": None}
    if c.review_required or c.parameters.get("candle_convention") != "reviewed_minute_ending_boundary":
        return {"status": "withheld", "reasons": ["explicit_candle_label_vs_close_time_review_required"], "probability": None}
    if len(evidence) != 1:
        raise ValueError("one exact financial source artifact required")
    rows = closed_candles(evidence[0], cutoff=cutoff, symbol=c.parameters["symbol"])
    if len(rows) < 720:
        raise ValueError("financial_minimum_720_closed_minutes_required")
    target = datetime.fromisoformat(c.parameters["resolution_boundary"])
    minutes = (target-cutoff).total_seconds()/60
    if not 1 <= minutes <= 1440:
        raise ValueError("financial_research_horizon_1min_to_24h_required")
    returns = [math.log(b[2]/a[2]) for a, b in pairwise(rows)]
    sigma = stdev(returns)
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError("financial_nonzero_measured_volatility_required")
    # Zero log-return drift baseline. No price-direction proxy is substituted for
    # this exact threshold and horizon. Fat tails/regime changes remain unmodeled.
    z = math.log(rows[-1][2]/c.parameters["threshold"]) / (sigma*math.sqrt(minutes))
    yes = 0.5 * (1 + math.erf(z/math.sqrt(2)))
    p = yes if c.parameters["selected_outcome"] == "Yes" else 1-yes
    source = DomainEvidence.model_validate(evidence[0].model_dump())
    config = {"zero_log_drift": True, "minimum_minutes": 720, "max_horizon_minutes": 1440,
              "candle_convention": c.parameters["candle_convention"]}
    return {"status": "research_estimate", "domain": "crypto", "contract_type": c.contract_type,
            "probability_semantics": "binary_event_probability", "probability": p,
            "model_version": MODEL_VERSION, "model_sha256": digest([hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), config]),
            "feature_version": FEATURE_VERSION, "dataset_sha256": digest([source.content_sha256]),
            "evidence_ids": [source.id], "independent_of_polymarket": True, "training_observations": len(rows),
            "measured_sigma_per_sqrt_minute": sigma, "forecast_horizon_seconds": minutes*60,
            "last_completed_candle": datetime.fromtimestamp(rows[-1][1]/1000, UTC).isoformat(),
            "uncertainty": {"lower_probability": 0.0, "upper_probability": 1.0,
                            "type": "uncalibrated_diffusion_assumption; no coverage guarantee",
                            "missing": ["jumps", "regime_change", "heldout_calibration", "tail_validation"]},
            "calibration_status": "unvalidated_research", "brier": None, "log_loss": None,
            "cost_adjusted_trading_edge": None, "trading_authority": False, "certification_authority": False}


class FinancialResearchModel:
    domain = "crypto"
    model_version = MODEL_VERSION
    supported_contract_types = ("binance_minute_terminal_close_above",)

    def forecast(self, contract, evidence, *, cutoff):
        return forecast_financial(contract, evidence, cutoff=cutoff)
