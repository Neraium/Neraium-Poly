"""Independent event research; exact rules and external evidence precede numbers."""

import hashlib
import math
import re
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import stdev
from zoneinfo import ZoneInfo

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.finance import digest, map_financial
from neraium_poly.research.phase18.sources import at, completed_minutes

MODEL_VERSION = "phase18-binance-daily-low-logdiffusion-v1"
FEATURE_VERSION = "complete-rule-window-and-prior720-closed-returns-v1"
ASSETS = {"Bitcoin": ("BTC", "BTCUSDT"), "Ethereum": ("ETH", "ETHUSDT")}


def daily_low_rules(name):
    asset, _symbol = ASSETS[name]
    return (
        f'This market will immediately resolve to "Yes" if any Binance 1 minute candle for {name} ({asset}/USDT) on the date specified in the title, between 12:00 AM ET and 11:59 PM ET has a final "Low" price equal to or lower than the price specified in the title. Otherwise, this market will resolve to "No."\n\n'
        f'The resolution source for this market is Binance, specifically the {asset}/USDT "Low" prices available at https://www.binance.com/en/trade/{asset}_USDT, with the chart settings on "1m" for one-minute candles selected on the top bar.\n\n'
        f'Please note that the outcome of this market depends solely on the price data from the Binance {asset}/USDT trading pair. Prices from other exchanges, different trading pairs, or spot markets will not be considered for the resolution of this market.'
    )


def map_event_contract(market, *, now):
    """Exact daily-Low template; ambiguous noon closes retain their old quarantine.

    Daily barrier and terminal-close events are different targets. No current
    probability, price or outcome-token identifier is used as a model feature.
    """
    now = at(now)
    m = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    matched = re.fullmatch(r"Will (Bitcoin|Ethereum) dip to \$((?:\d{1,3}(?:,\d{3})+|\d+)) on ([A-Z][a-z]+ \d{1,2})\?", m.question)
    reasons, params = [], {}
    if m.exchange != "polymarket" or m.source != "https://gamma-api.polymarket.com":
        reasons.append("exact_polymarket_metadata_source_required")
    if (m.timestamp > now or m.available_at > now or m.status != "active"
        or not m.end_time or m.end_time <= now or m.outcome not in {"Yes", "No"}):
        reasons.append("causal_active_future_binary_event_required")
    if matched and not reasons:
        name, threshold_raw, date = matched.groups()
        asset, symbol = ASSETS[name]
        threshold = float(threshold_raw.replace(",", ""))
        local_end = m.end_time.astimezone(ZoneInfo("America/New_York"))
        try:
            day = datetime.strptime(f"{(local_end-timedelta(days=1)).year} {date}", "%Y %B %d").replace(tzinfo=ZoneInfo("America/New_York"))
        except ValueError:
            reasons.append("valid_exact_event_date_required")
            day = None
        if (not math.isfinite(threshold) or threshold <= 0 or not day
            or local_end != day+timedelta(days=1)
            or not day.astimezone(UTC) <= now < local_end.astimezone(UTC)):
            reasons.append("daily_window_not_started_or_end_mismatch")
        if (m.resolution_source != f"https://www.binance.com/en/trade/{asset}_USDT"
            or m.resolution_rules != daily_low_rules(name)):
            reasons.append("exact_daily_low_rule_reference_required")
        if not reasons:
            params = {"asset": asset, "symbol": symbol, "quote_currency": "USDT",
                "threshold": threshold, "operator": "<=", "selected_outcome": m.outcome,
                "price_definition": "final_minute_low", "timezone": "America/New_York",
                "period_start_utc": day.astimezone(UTC).isoformat(),
                "period_end_utc": local_end.astimezone(UTC).isoformat(),
                "candle_convention": "all_UTC_1m_candles_with_open_in_half_open_local_day",
                "market_snapshot": m.model_dump(mode="json"), "reference_source": m.resolution_source}
    elif not matched:
        # Do not silently pick minute-opening labels or minute-ending boundaries.
        try:
            old = map_financial(m, now=now)
            if old.contract_type == "binance_minute_terminal_close_above":
                return old
        except ValueError:
            pass
        reasons.append("unsupported_event_rule_template_or_domain")
    return DomainContract(id=digest(["phase18-exact-daily-low", m.id, m.resolution_rules]),
        timestamp=now, available_at=now, source="neraium-poly/event-rule-interpreter/v18",
        domain="crypto" if matched else "other", event_id=m.event_id, market_id=m.market_id,
        token_id=m.token_id, contract_type="binance_daily_low_barrier" if not reasons else "unsupported_event",
        probability_semantics="binary_event_probability" if not reasons else "unsupported",
        rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(), parameters=params,
        compatible=not reasons, review_required=bool(reasons), reasons=tuple(reasons))


def _withheld(reason, domain=None):
    return {"status": "withheld", "domain": domain, "probability": None,
        "lower_probability": None, "upper_probability": None, "reasons": [reason],
        "calibration_status": "unavailable", "brier": None, "log_loss": None,
        "independent_of_polymarket": False, "trading_authority": False, "certification_authority": False}


def forecast_event(contract, evidence, *, cutoff):
    """Return a conditional research probability only after causal source replay.

    The daily-low model is a continuous zero-log-drift diffusion approximation,
    not a discrete-calibrated market probability or supported trading advantage.
    Unknown calibration is reflected by containing uncertainty bounds [0,1].
    """
    try:
        c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
        cutoff = at(cutoff)
        if c.timestamp > cutoff or c.available_at > cutoff or not c.compatible or c.review_required:
            return _withheld("reviewed_causal_exact_contract_required", c.domain)
        if c.domain == "weather":
            return _withheld("weather_station_window_matched_calibrated_predictive_distribution_required", c.domain)
        if c.domain == "economics":
            return _withheld("initial_release_vintages_and_independent_validated_probability_model_required", c.domain)
        if c.domain != "crypto" or c.contract_type != "binance_daily_low_barrier":
            return _withheld("unsupported_or_ambiguous_terminal_convention", c.domain)
        if c.probability_semantics != "binary_event_probability":
            return _withheld("binary_event_probability_semantics_required", c.domain)
        # Rebind every parameter to the original full rule, question and window.
        original = MarketSnapshot.model_validate(c.parameters["market_snapshot"])
        rebound = map_event_contract(original, now=cutoff)
        if (not rebound.compatible or rebound.review_required or rebound.parameters != c.parameters
            or rebound.rules_sha256 != c.rules_sha256
            or (c.market_id, c.event_id, c.token_id) != (original.market_id, original.event_id, original.token_id)):
            return _withheld("contract_parameter_or_original_rule_binding_failed", c.domain)
        if not isinstance(evidence, (list, tuple)) or len(evidence) != 1:
            return _withheld("one_exact_independent_crypto_source_required", c.domain)
        source = DomainEvidence.model_validate(evidence[0].model_dump() if isinstance(evidence[0], DomainEvidence) else evidence[0])
        candles = completed_minutes(source, cutoff=cutoff, symbol=c.parameters["symbol"])
        if len(candles) < 721:
            return _withheld("minimum720_completed_log_returns_required", c.domain)
        start, end = at(c.parameters["period_start_utc"]), at(c.parameters["period_end_utc"])
        start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
        window = [r for r in candles if start_ms <= r["open_ms"] < end_ms]
        if not window or window[0]["open_ms"] != start_ms or window[-1]["close_ms"] != source.payload["end_ms"]:
            return _withheld("complete_elapsed_settlement_window_required", c.domain)
        threshold = c.parameters["threshold"]
        if min(r["low"] for r in window) <= threshold:
            return _withheld("event_barrier_already_observed_before_forecast", c.domain)
        remaining = (end-cutoff).total_seconds()/60
        if not 1 <= remaining <= 1440:
            return _withheld("forecast_horizon1min_to24h_required", c.domain)
        training = candles[-721:]
        returns = [math.log(b["close"]/a["close"]) for a, b in pairwise(training)]
        sigma = stdev(returns)
        if not math.isfinite(sigma) or sigma <= 0:
            return _withheld("positive_measured_return_variation_required", c.domain)
        reference = training[-1]["close"]
        if reference <= threshold:
            return _withheld("event_barrier_already_observed_before_forecast", c.domain)
        minutes = (end.timestamp()*1000-training[-1]["close_ms"])/60000
        # Reflection principle for zero-drift log Brownian lower barrier.
        z = math.log(threshold/reference)/(sigma*math.sqrt(minutes))
        yes = min(1., max(0., math.erfc(-z/math.sqrt(2))))
        probability = yes if c.parameters["selected_outcome"] == "Yes" else 1-yes
        config = {"zero_log_drift": True, "minimum_returns": 720, "horizon_max_minutes": 1440,
                  "first_passage_continuous_approximation": True, "uncertainty_bounds": [0., 1.]}
        implementation_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        source_sha = hashlib.sha256(Path(__file__).with_name("sources.py").read_bytes()).hexdigest()
        model_sha = digest([implementation_sha, source_sha, config])
        return {"status": "research_estimate", "domain": "crypto", "contract_type": c.contract_type,
            "event_id": c.event_id, "market_id": c.market_id, "token_id": c.token_id,
            "probability_semantics": "binary_event_probability", "probability": probability,
            "lower_probability": 0., "upper_probability": 1., "reasons": [],
            "model_version": MODEL_VERSION, "model_sha256": model_sha, "feature_version": FEATURE_VERSION,
            "source_implementation_sha256": source_sha, "forecast_implementation_sha256": implementation_sha,
            "dataset_sha256": digest([source.content_sha256]), "evidence_ids": [source.id],
            "rules_sha256": c.rules_sha256, "evidence_cutoff": cutoff.isoformat(),
            "independent_of_polymarket": True, "training_observations": len(training),
            "training_returns": len(returns), "elapsed_window_candles": len(window),
            "reference_price": reference, "reference_timestamp": datetime.fromtimestamp(training[-1]["close_ms"]/1000, UTC).isoformat(),
            "reference_age_seconds": cutoff.timestamp()-training[-1]["close_ms"]/1000,
            "measured_sigma_per_sqrt_minute": sigma, "forecast_horizon_seconds": remaining*60,
            "calibration_status": "unvalidated_research", "brier": None, "log_loss": None,
            "uncertainty": {"lower_probability": 0., "upper_probability": 1.,
                "type": "uncalibrated_model_assumptions_not_a_coverage_interval",
                "missing": ["independent_event_calibration", "jumps", "volatility_regime_change", "discrete_source_validation"]},
            "limitations": ["Continuous first-passage approximation of a final-minute-Low event",
                "Past return volatility is not a calibrated future distribution",
                "Extreme tails/complements may round to0or1; this is not empirical certainty",
                "No Polymarket prices are predictive features; market baseline comparison is external",
                "No demonstrated forecasting superiority, independent sample sufficiency or trading edge"],
            "cost_adjusted_trading_edge": None, "research_only": True,
            "trading_authority": False, "certification_authority": False}
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return _withheld(str(error)[:160])
