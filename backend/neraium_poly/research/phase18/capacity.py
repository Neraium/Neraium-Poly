"""Nonlinear displayed-depth capacity scenarios, never new capital or fill authority."""

from math import isfinite

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.convergence import _at

CAPITALS = (500, 1000, 10000, 100000, 1000000)


def _number(value, low=0, high=float("inf")):
    return type(value) in (int, float) and isfinite(value) and low <= value <= high


def _walk(levels, requested, *, participation=.1, lower=None, fee=None, reserved=0, notional_limit=float("inf")):
    remaining, quantity, principal, edge_limited = requested, 0., 0., False
    consumed = reserved
    for level in levels:
        capacity = level.size*participation
        already = min(capacity, consumed)
        capacity -= already
        consumed -= already
        edge = lower*(1-fee)-level.price*(1+fee)-.02 if lower is not None and fee is not None else None
        if edge is not None and edge < .03:
            edge_limited = True
            break
        take = min(remaining, capacity, max(0., notional_limit-principal)/level.price)
        quantity += take
        principal += take*level.price
        remaining -= take
        if remaining <= 1e-9 or principal >= notional_limit-1e-9:
            break
    return {"supported_shares": quantity, "unsupported_shares": max(0., requested-quantity),
            "modeled_entry_notional": principal, "entry_vwap": principal/quantity if quantity else None,
            "full_requested_quantity_supported": requested-quantity <= 1e-9, "edge_limited": edge_limited}


def capacity_scenarios(opportunity, book, *, bankrolls=CAPITALS):
    """Compare finite depth against hypothetical20%capital demand, not recommended bets.

    Existing approved tier maxima stay5/15/25 at every capital level. The larger
    scenario demand is a stress test outside these approved sizes, with no account
    creation, risk approval, order, fill or hypothetical portfolio P/L.
    """
    op = opportunity if isinstance(opportunity, dict) else {}
    result = {"schema_version": "phase18-capacity-v1", "status": "withheld", "reasons": [],
        "scenarios": [], "hypothetical_capital_only": True, "accounts_created": 0,
        "trading_authority": False, "certification_authority": False, "actual_fill": False,
        "net_pnl": None, "net_return": None, "drawdown": None,
        "capital_turnover": None, "risk_adjusted_performance": None, "confidence_interval": None}
    try:
        if (not isinstance(bankrolls, (list, tuple)) or not 1 <= len(bankrolls) <= 16
            or any(not _number(v, 1, 1e9) for v in bankrolls) or len(set(bankrolls)) != len(bankrolls)):
            raise ValueError("bounded_distinct_hypothetical_capitals_required")
        b = book if isinstance(book, OrderBookSnapshot) else OrderBookSnapshot.model_validate(book)
        if (len(b.asks) > 1000 or len(b.bids) > 1000
            or len({p.price for p in b.asks}) != len(b.asks) or len({p.price for p in b.bids}) != len(b.bids)):
            raise ValueError("bounded_unique_order_book_levels_required")
        cutoff = _at(op["evaluated_at"])
        health = assess_book(b, cutoff, expected_token=op.get("token_id"), max_spread=.05)
        if (not health.healthy or b.source not in PUBLIC_BOOK_SOURCES or b.exchange != "polymarket"
            or not 0 <= (cutoff-b.available_at).total_seconds() <= 15):
            raise ValueError("fresh_authentic_two_sided_depth_required")
        if (op.get("market_id") != b.market_id or op.get("token_id") != b.token_id
            or op.get("book_id") != b.id or op.get("book_sha256") != digest(b.model_dump(mode="json"))):
            raise ValueError("opportunity_exact_book_binding_required")
        reserved = op.get("already_committed_shares", 0)
        if not _number(reserved):
            raise ValueError("finite_nonnegative_crowding_required")
        fee, lower = op.get("fee_rate"), op.get("lower_probability")
        qualified = (op.get("research_qualified") is True and _number(fee, 0, 1)
                     and _number(lower, 0, 1) and _number(op.get("qualified_net_edge"), .03, 1)
                     and _number(op.get("min_order_size"), 1e-9))
        if not qualified:
            fee = lower = None
        total_ask = max(0., sum(p.size*.1 for p in b.asks)-reserved)
        total_bid = max(0., sum(p.size*.1 for p in b.bids)-reserved)
        edge_capacity = _walk(b.asks, total_ask, lower=lower, fee=fee, reserved=reserved)
        end = _at(op["end_time"]) if op.get("end_time") else None
        lockup = (end-cutoff).total_seconds() if end and end > cutoff else None
        result.update(status="qualified_research_capacity" if qualified else "liquidity_only_unqualified",
            book_id=b.id, book_sha256=digest(b.model_dump(mode="json")), evaluated_at=cutoff.isoformat(),
            total_observed_ask_participating_shares=total_ask,
            total_observed_bid_participating_shares=total_bid,
            edge_supported_shares=edge_capacity["supported_shares"] if qualified else None,
            edge_supported_notional=edge_capacity["modeled_entry_notional"] if qualified else None,
            edge_disappearance_observed=edge_capacity["edge_limited"] if qualified else None,
            capacity_beyond_observed_depth=None,
            expected_capital_lockup_seconds=lockup, approved_tier_notional_caps={"standard":5,"high":15,"exceptional":25},
            liquidity_participation=.1, risk_maximum_participation=.25,
            queue_position_verified=False, entry_after_latency_verified=False,
            future_exit_liquidity_verified=False)
        for capital in bankrolls:
            demand = .2*capital
            shares = demand/b.asks[0].price
            walk = _walk(b.asks, shares, lower=lower, fee=fee, reserved=reserved, notional_limit=.1*capital)
            principal = walk["modeled_entry_notional"]
            lot_supported = walk["supported_shares"]+1e-9 >= op.get("min_order_size", float("inf"))
            net = lower*(1-fee)*walk["supported_shares"]-principal*(1+fee)-.02*walk["supported_shares"] if qualified and lot_supported and principal >= 2-1e-9 else None
            result["scenarios"].append({"hypothetical_bankroll": capital,
                "hypothetical20percent_demand_notional": demand,
                "hypothetical10percent_event_correlation_notional_cap": .1*capital, "minimum_lot_supported": lot_supported, "minimum_notional_supported": principal >= 2-1e-9, "requested_shares_at_best_ask": shares,
                **walk, "partial_depth": not walk["full_requested_quantity_supported"],
                "hypothetical_capital_utilization": principal/capital,
                "entry_sweep_impact_per_share": walk["entry_vwap"]-b.asks[0].price if walk["entry_vwap"] else None,
                "conditional_expected_net_value": net,
                "conditional_net_edge_per_share": net/walk["supported_shares"] if net is not None and walk["supported_shares"] else None,
                "current_bid_exit_shares_supported": min(walk["supported_shares"],total_bid),
                "future_exit_capacity": None, "crowding_reserved_shares": reserved,
                "unmodeled_crowding": "Other strategies must share the same book; no extra liquidity is created",
                "event_exposure_fraction_if_one_event": principal/capital,
                "scenario_demand_is_order_authorized": False,
                "existing_single_order_approved_caps_unchanged": True,
                "conditional_ev_is_not_verified_profit": True})
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        result["reasons"] = [str(error)[:160]]
    result["limitations"] = ["Scenarios are not accounts, actual fills, positions or paper performance",
        "Hypothetical20%capital demand does not relax existing event/correlation/single-position limits",
        "Anonymous displayed depth cannot prove queue priority, entry survival after latency or future exit liquidity",
        "Unqualified forecasts produce only observed liquidity metrics and null expected value",
        "Capital lockup follows known contract end only; actual settlement delay and disputes remain unknown"]
    return result
