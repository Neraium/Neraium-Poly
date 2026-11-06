"""Conservative cost research never grants experimental strategy or order authority."""

from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES, verified_fee_rate


def assess_domain_opportunity(forecast, contract, market, book, *, now, fees=None, authorized=False):
    reasons = []
    if not authorized:
        reasons.append("domain_strategy_not_authorized_for_experimental_admission")
    if forecast.research_only:
        reasons.append("domain_model_research_only")
    if forecast.calibration_status != "independently_validated":
        reasons.append("independent_domain_calibration_required")
    if not contract.compatible or contract.review_required:
        reasons.append("reviewed_domain_rules_required")
    if (
        forecast.timestamp > now
        or forecast.evidence_cutoff > forecast.timestamp
        or (now - forecast.timestamp).total_seconds() > 300
    ):
        reasons.append("fresh_causal_domain_forecast_required")
    if (forecast.event_id, forecast.market_id, forecast.token_id) != (
        market.event_id,
        market.market_id,
        market.token_id,
    ):
        reasons.append("domain_market_identity_mismatch")
    health = assess_book(book, now, expected_token=market.token_id, max_spread=0.05)
    reasons.extend(health.reasons)
    if book and (
        book.source not in PUBLIC_BOOK_SOURCES
        or book.exchange != "polymarket"
        or book.market_id != market.market_id
    ):
        reasons.append("authentic_domain_book_required")
    lower = forecast.uncertainty.get("lower_probability")
    upper = forecast.uncertainty.get("upper_probability")
    if lower is None or upper is None or upper - lower > 0.35:
        reasons.append("qualified_bounded_domain_uncertainty_required")
    if forecast.probability_semantics != "binary_event_probability":
        reasons.append("separate_nonbinary_execution_semantics_required")
    fee = verified_fee_rate(fees or {}, now)
    if fee is None:
        reasons.append("verified_current_domain_fee_required")
    edge = None
    if book and book.asks and fee is not None and lower is not None:
        edge = lower - book.asks[0].price * (1 + fee) - 0.02
        if edge < 0.03:
            reasons.append("cost_uncertainty_adjusted_domain_edge_insufficient")
        quantity = max(2 / book.asks[0].price, market.min_order_size)
        if quantity * book.asks[0].price > 5 or quantity > book.asks[0].size * 0.1:
            reasons.append("domain_standard_size_or_depth_limit")
    reasons.append("terminal_domain_execution_capability_not_approved")
    return {
        "eligible": False,
        "estimated_net_edge": edge,
        "reasons": sorted(set(reasons)),
        "risk_evaluated": False,
        "order_attempted": False,
        "trading_authority": False,
    }
