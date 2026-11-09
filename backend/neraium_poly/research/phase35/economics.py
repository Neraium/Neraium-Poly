"""Decision-snapshot conditional research economics; never execution authority."""

from __future__ import annotations

import math
from datetime import datetime

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase29.costs import replay_fee

CAPITAL_SCENARIOS = (500, 1000, 10000, 100000, 1000000)


def _time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("aware decision timestamp required")
    return result


def depth_capacity(
    asks, *, probability, lower_probability, upper_probability, fee_rate, bankroll, participation=0.1
):
    """Consume distinct displayed price levels; exact native fee curve, no fills.

    A maximum20% capital scenario is illustrative, not an account risk change.
    Stop at nonpositive conditional point headroom. Lower bound uses the SAME
    hypothetical quantity; uncertainty cannot be hidden by optimizing each bound.
    """
    values = (probability, lower_probability, upper_probability, fee_rate, bankroll, participation)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("finite economic inputs required")
    if (
        not 0 <= lower_probability <= probability <= upper_probability <= 1
        or not 0 <= fee_rate <= 1
        or bankroll <= 0
        or not 0 < participation <= 0.1
    ):
        raise ValueError("bounded research assumptions required")
    seen = set()
    prior = 0.0
    capital = bankroll * 0.2
    rows = []
    for level in asks:
        price, size = level["price"], level["size"]
        if (
            type(price) not in (int, float)
            or type(size) not in (int, float)
            or not math.isfinite(price)
            or not math.isfinite(size)
            or not 0 < price < 1
            or size <= 0
            or price < prior
            or price in seen
        ):
            raise ValueError("ordered unique authentic ask levels required")
        seen.add(price)
        prior = price
        fee_per_share = fee_rate * price * (1 - price)
        if probability <= price + fee_per_share:
            continue
        quantity = min(size * participation, max(0.0, capital) / (price + fee_per_share))
        if quantity <= 1e-12:
            continue
        acquisition = quantity * price
        fee = quantity * fee_per_share
        capital -= acquisition + fee
        rows.append(
            {
                "price": price,
                "displayed_quantity": size,
                "participating_quantity": quantity,
                "acquisition_cost": acquisition,
                "protocol_fee_before_rounding": fee,
            }
        )
    quantity = math.fsum(r["participating_quantity"] for r in rows)
    acquisition = math.fsum(r["acquisition_cost"] for r in rows)
    fee = math.fsum(r["protocol_fee_before_rounding"] for r in rows)
    spend = acquisition + fee
    return {
        "bankroll_hypothetical": bankroll,
        "capital_fraction": 0.2,
        "participation": participation,
        "levels": rows,
        "supported_quantity": quantity,
        "acquisition_cost": acquisition,
        "protocol_fee_before_rounding": fee,
        "capital_with_protocol_fee": spend,
        "conditional_gross_point_headroom": quantity * probability - acquisition,
        "conditional_point_headroom_after_protocol_fee": quantity * probability - spend,
        "native_headroom_bounds_before_unverified_costs": [
            quantity * lower_probability - spend,
            quantity * upper_probability - spend,
        ],
        "maximum_acquisition_loss_before_unverified_costs": spend,
        "capital_utilization": spend / bankroll,
        "actual_fill": False,
        "guaranteed_capacity": False,
    }


def weather_economics(forecast, evidence, fee_observation, fee_records, *, as_of):
    """Reproduce original weather model/book and fee evidence at creation time.

    Later calling time never makes a stale snapshot current or permits later fee
    evidence to enter the original decision. Native payout bounds remain [0,1]
    for conditional/unvalidated forecasts; this report is rejected for admission.
    """
    from neraium_poly.research.phase35.weather import replay

    created = _time(forecast["timestamp"])
    if created > _time(as_of):
        raise ValueError("decision not yet available")
    replay(forecast, evidence, as_of=as_of)
    proof = replay_fee(fee_observation, fee_records, token_id=forecast["token_id"], as_of=created.isoformat())
    if proof.get("status") != "verified_current_protocol_curve":
        raise ValueError("decision_time_native_fee_unavailable:" + proof.get("reason", "unknown"))
    book = forecast["book"]
    if not _time(book["timestamp"]) <= _time(book["available_at"]) <= created:
        raise ValueError("book unavailable at original decision")
    if (
        book["market_id"] != forecast["market_id"]
        or book["token_id"] != forecast["token_id"]
        or digest(book) != forecast["book_sha256"]
    ):
        raise ValueError("original economic identity mismatch")
    conditional = not forecast.get("unconditional_contract_probability", False)
    if conditional or forecast.get("calibration_status") != "validated":
        lower, upper = 0.0, 1.0
    else:
        lower, upper = forecast["lower_probability"], forecast["upper_probability"]
    scenarios = [
        depth_capacity(
            book["asks"],
            probability=forecast["probability"],
            lower_probability=lower,
            upper_probability=upper,
            fee_rate=proof["rate"],
            bankroll=bankroll,
        )
        for bankroll in CAPITAL_SCENARIOS
    ]
    return {
        "status": "economically_evaluated_research_snapshot",
        "forecast_sha256": digest(forecast),
        "model_id": forecast["model_id"],
        "market_id": forecast["market_id"],
        "event_id": forecast["event_id"],
        "token_id": forecast["token_id"],
        "decision_at": forecast["timestamp"],
        "book_source_at": book["timestamp"],
        "book_available_at": book["available_at"],
        "book_sha256": forecast["book_sha256"],
        "conditional_probability": forecast["probability"],
        "native_probability_bounds": [lower, upper],
        "fee_proof": proof,
        "fee_formula": "quantity * fd.r * price * (1-price)",
        "scenarios": scenarios,
        "rejections": [
            "unconditional_native_probability_unqualified",
            "calibration_unvalidated",
            "all_in_execution_costs_unverified",
            "research_strategy_has_no_execution_authority",
        ],
        "conditional_point_estimate_is_validated_edge": False,
        "all_in_costs_verified": False,
        "net_profit_verified": False,
        "current_executable_opportunity": False,
        "actual_fill": False,
        "research_only": True,
        "trading_authority": False,
        "limitations": [
            "Original decision snapshot only; no current depth or fill guarantee",
            "Both weather challengers share one AWC lineage and one event; do not aggregate capacity",
            "Fees before rounding; unknown fill fragmentation, latency, additional slippage, capital lockup and settlement costs",
            "Native lower bound remains zero; conditional point headroom is not conservative net expected profit",
        ],
    }
