"""Fail-closed event opportunity assessment; no order or account mutation."""

import hashlib

from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES, verified_fee_rate


def assess_event_proposal(forecast, market, book, *, now, fee_schedule=None, enabled=False):
    reasons = []
    if forecast.kind != "independent_model":
        reasons.append("independent_event_forecast_required")
    if (
        forecast.available_at > now
        or forecast.timestamp > now
        or forecast.evidence_cutoff > forecast.timestamp
    ):
        reasons.append("noncausal_event_forecast")
    if (now - forecast.timestamp).total_seconds() > 300:
        reasons.append("stale_event_forecast")
    if hashlib.sha256(market.resolution_rules.encode()).hexdigest() != forecast.resolution_rules_sha256:
        reasons.append("event_resolution_rules_changed")
    if book is not None and (
        book.market_id != forecast.market_id
        or book.exchange != "polymarket"
        or book.source not in PUBLIC_BOOK_SOURCES
    ):
        reasons.append("authentic_identity_matched_event_book_required")
    if forecast.calibration_status != "independently_validated":
        reasons.append("independent_event_calibration_required")
    if forecast.lower_probability is None or forecast.upper_probability is None:
        reasons.append("bounded_event_uncertainty_required")
    elif forecast.upper_probability - forecast.lower_probability > 0.35:
        reasons.append("event_uncertainty_too_wide")
    if not enabled:
        reasons.append("event_strategy_not_enabled_for_experimental_operation")
    if (market.market_id, market.token_id, market.event_id) != (
        forecast.market_id,
        forecast.token_id,
        forecast.event_id,
    ):
        reasons.append("event_market_identity_mismatch")
    if market.status != "active" or not market.resolution_rules or not market.resolution_source:
        reasons.append("event_resolution_rules_unavailable")
    if market.end_time is not None and market.end_time <= now:
        reasons.append("event_already_ended")
    health = assess_book(book, now, expected_token=forecast.token_id, max_spread=0.05)
    reasons.extend(health.reasons)
    fee = verified_fee_rate(fee_schedule or {}, now)
    if fee is None:
        reasons.append("current_verified_event_fee_required")
    edge = None
    if book is not None and book.asks and fee is not None and forecast.lower_probability is not None:
        # Research bound only: unresolved settlement costs are not assumed zero.
        edge = forecast.lower_probability - book.asks[0].price * (1 + fee) - 0.02
        if edge < 0.03:
            reasons.append("uncertainty_adjusted_event_edge_insufficient")
        quantity = max(2 / book.asks[0].price, market.min_order_size)
        if quantity * book.asks[0].price > 5 or quantity > book.asks[0].size * 0.1:
            reasons.append("event_standard_size_or_liquidity_limit")
    # Existing isolated account supports horizon marks only. Never reinterpret
    # settlement probabilities as future bids to evade its execution/risk guard.
    reasons.append("terminal_event_execution_capability_not_approved")
    return {
        "forecast_id": forecast.id,
        "eligible": False,
        "estimated_net_edge": edge,
        "reasons": sorted(set(reasons)),
        "risk_evaluated": False,
        "order_attempted": False,
        "certification_authority": False,
    }
