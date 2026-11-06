"""Conservative observed-depth research; never order or probability authority.

The current broker submits a best-ask limit. Deeper asks are reported only as a
separate hypothetical sweep and cannot make that limit appear executable.
"""

from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from urllib.parse import urlparse

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book

PUBLIC_BOOK_SOURCES = {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
EPS = 1e-8
POLICY = {"source_max_age_seconds": 15, "market_max_age_seconds": 3600,
          "fee_max_age_seconds": 300, "max_spread": .05, "participation": .25,
          "slippage_per_share_per_leg": .01, "minimum_net_edge_per_share": .03,
          "standard_min_notional": 2, "standard_max_notional": 5}


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


def depth_walk(levels, quantity, *, participation=.25):
    """A conservative fractional-depth quote, not an execution or fill claim."""
    if not _finite(quantity) or quantity <= 0 or not _finite(participation) or not 0 < participation <= .25:
        raise ValueError("positive shares and conservative participation required")
    if not isinstance(levels, (list, tuple)) or len(levels) > 1000:
        raise ValueError("bounded observed depth required")
    remaining, value, used = quantity, 0., []
    for level in levels:
        price, size = (level["price"], level["size"]) if isinstance(level, dict) else (level.price, level.size)
        if not _finite(price) or not _finite(size) or not 0 < price < 1 or size <= 0:
            raise ValueError("invalid observed depth")
        take = min(remaining, size * participation)
        value += price * take
        if take > EPS:
            used.append({"price": price, "gross_observed_size": size, "modeled_shares": take})
        remaining -= take
        if remaining <= EPS:
            break
    filled = max(0., quantity - remaining)
    return {"requested_shares": quantity, "depth_supported_shares": filled,
            "unavailable_shares": max(0., remaining), "complete": remaining <= EPS,
            "vwap": value / filled if filled > EPS else None, "notional": value,
            "levels_used": used, "participation": participation,
            "semantics": "observed_fractional_depth_quote_not_a_simulated_fill"}


def _fee(observation, token, now):
    if not isinstance(observation, dict):
        return None, "fee_observation_missing"
    try:
        value = observation.get("fee_rate", observation.get("effective_notional_bound"))
        at = datetime.fromisoformat(observation.get("observed_at", observation.get("available_at", observation.get("timestamp", ""))))
        source = urlparse(observation["source"])
        if (not _finite(value) or not 0 <= value <= 1 or at.tzinfo is None
            or not 0 <= (now - at).total_seconds() <= POLICY["fee_max_age_seconds"]
            or source.scheme != "https" or source.hostname != "clob.polymarket.com"
            or source.port not in (None, 443) or source.username or source.password
            or not observation.get("reference")
            or observation.get("token_id", token) != token):
            raise ValueError("invalid fee provenance")
        return float(value), None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "fee_observation_stale_or_unverified"


def assess_execution(market, book, *, now, target_notional=2, fee_observation=None, forecast_lower_bid=None):
    """Audit a standard-size BUY using current data and conservative modeled costs.

    Result may withhold an existing strategy's candidate; it cannot approve one.
    Forecast values are monetary future-bid marks, not event probabilities.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("aware execution cutoff required")
    now = now.astimezone(UTC)
    result = {"schema_version": "phase16-executable-depth-v1", "evaluated_at": now.isoformat(),
              "research_only": True, "trading_authority": False, "certification_authority": False,
              "policy": dict(POLICY), "execution_checks_pass": False, "cost_adjusted_edge_pass": False,
              "estimated_net_edge_per_share": None, "reasons": [], "execution_reasons": [],
              "valuation_reasons": [], "future_exit_liquidity_verified": False, "settlement_rule_review_verified": False,
              "probability_semantics": "future_executable_bid_mark_USD_per_share_not_terminal_probability"}
    try:
        market = market if isinstance(market, MarketSnapshot) else MarketSnapshot.model_validate(market)
        book = book if isinstance(book, OrderBookSnapshot) else OrderBookSnapshot.model_validate(book)
    except (TypeError, ValueError):
        result.update(status="withheld", reasons=["invalid_or_missing_market_or_book_contract"],
                      execution_reasons=["invalid_or_missing_market_or_book_contract"])
        return result
    reasons = result["execution_reasons"]
    reasons.extend(assess_book(book, now, max_spread=POLICY["max_spread"], expected_token=market.token_id).reasons)
    if book.source not in PUBLIC_BOOK_SOURCES or market.source != "https://gamma-api.polymarket.com":
        reasons.append("unverified_public_source")
    if (book.market_id, book.exchange) != (market.market_id, market.exchange) or market.exchange != "polymarket":
        reasons.append("market_book_identity_mismatch")
    if market.timestamp > now or market.available_at > now:
        reasons.append("future_market_context")
    elif (now - market.timestamp).total_seconds() > POLICY["market_max_age_seconds"]:
        reasons.append("stale_market_context")
    if market.status != "active" or not market.resolution_rules or not market.resolution_source or not market.event_id:
        reasons.append("missing_active_status_parent_or_resolution_rules")
    if market.end_time and market.end_time <= now:
        reasons.append("market_ended")
    if (not _finite(target_notional)
        or not POLICY["standard_min_notional"] <= target_notional <= POLICY["standard_max_notional"]):
        reasons.append("unsupported_research_notional_tier")
    fee, fee_reason = _fee(fee_observation, market.token_id, now)
    if fee_reason:
        reasons.append(fee_reason)
    evidence_id = fee_observation.get("evidence_id") if isinstance(fee_observation, dict) else None
    evidence_id = evidence_id if isinstance(evidence_id, str) and len(evidence_id) <= 256 else None
    raw_ids = fee_observation.get("raw_response_ids", []) if isinstance(fee_observation, dict) else []
    raw_ids = [v for v in raw_ids[:20] if isinstance(v, str) and 0 < len(v) <= 256] if isinstance(raw_ids, (list, tuple)) else []
    result.update(market_id=market.market_id, token_id=market.token_id, event_id=market.event_id,
                  book_id=book.id, source=book.source, source_at=book.timestamp.isoformat(),
                  available_at=book.available_at.isoformat(), source_age_seconds=(now-book.timestamp).total_seconds(),
                  book_sha256=sha256(book.model_dump_json().encode()).hexdigest(),
                  market_sha256=sha256(market.model_dump_json().encode()).hexdigest(),
                  resolution_rules_sha256=sha256(market.resolution_rules.encode()).hexdigest(),
                  fee_rate=fee, fee_evidence_id=evidence_id, raw_fee_response_ids=raw_ids,
                  target_notional=target_notional if _finite(target_notional) else None)
    if book.bids and book.asks and _finite(target_notional) and target_notional > 0:
        ask, bid = book.asks[0].price, book.bids[0].price
        quantity = max(target_notional / ask, market.min_order_size)
        entry = depth_walk(book.asks, quantity)
        exit_quote = depth_walk(book.bids, quantity)
        limit_depth = sum(v.size for v in book.asks if v.price <= ask + EPS) * POLICY["participation"]
        if quantity > limit_depth + EPS:
            reasons.append("best_ask_limit_participation_insufficient")
        if not entry["complete"]:
            reasons.append("observed_ask_depth_insufficient")
        if not exit_quote["complete"]:
            reasons.append("current_bid_exit_depth_insufficient")
        notional = quantity * ask
        if not POLICY["standard_min_notional"] - EPS <= notional <= POLICY["standard_max_notional"] + EPS:
            reasons.append("minimum_order_exceeds_standard_notional")
        if abs(ask / market.tick_size - round(ask / market.tick_size)) > EPS:
            reasons.append("price_tick_mismatch")
        result.update(quantity_shares=quantity, current_best_bid=bid, current_best_ask=ask,
                      spread=ask-bid, broker_limit_price=ask, broker_limit_capacity_shares=limit_depth,
                      broker_limit_notional=notional,
                      broker_fee_inclusive_reservation=notional * (1+fee) if fee is not None else None,
                      hypothetical_sweep_entry=entry, current_exit_depth_proxy=exit_quote,
                      current_exit_is_not_future_liquidity=True)
        if _finite(forecast_lower_bid) and 0 <= forecast_lower_bid <= 1 and entry["complete"] and exit_quote["complete"] and fee is not None:
            # Current curvature is only an explicit conservative proxy for future
            # exit impact; source books at execution time remain mandatory.
            entry_impact = max(0., entry["vwap"] - ask)
            exit_impact = max(0., bid - exit_quote["vwap"])
            lower_exit = max(0., forecast_lower_bid - exit_impact)
            edge = lower_exit*(1-fee) - entry["vwap"]*(1+fee) - .02
            result.update(forecast_lower_bid=forecast_lower_bid, depth_adjusted_lower_exit_bid=lower_exit,
                          estimated_net_edge_per_share=edge, entry_impact_per_share=entry_impact,
                          exit_impact_proxy_per_share=exit_impact,
                          entry_fee_per_share=entry["vwap"]*fee, exit_fee_per_share=lower_exit*fee,
                          roundtrip_slippage_per_share=.02,
                          cost_adjusted_edge_pass=edge >= POLICY["minimum_net_edge_per_share"] - EPS)
            if edge < POLICY["minimum_net_edge_per_share"] - EPS:
                result["valuation_reasons"].append("depth_cost_adjusted_edge_insufficient")
        else:
            result["valuation_reasons"].append("qualified_forecast_or_depth_cost_inputs_missing")
    result["execution_reasons"] = sorted(set(reasons))
    result["execution_checks_pass"] = not reasons
    result["reasons"] = sorted(set(reasons + result["valuation_reasons"]))
    result["status"] = "withheld" if result["reasons"] else "execution_supported_research_valuation_only"
    result["assumptions"] = ["existing broker submits best-ask limit; deeper asks cannot authorize that order",
                             "25% per-level fractional depth and $.01/share per-leg slippage",
                             "current bid curvature is a future-exit proxy, not verified future liquidity",
                             "resolution metadata presence is not independent settlement-rule review",
                             "no reservation, latency fill, queue position or order is created by this assessment"]
    return result
