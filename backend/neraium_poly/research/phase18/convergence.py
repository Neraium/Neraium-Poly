"""Evidence convergence is research qualification, never order authority."""

from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from urllib.parse import urlsplit

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES, verified_fee_rate
from neraium_poly.research.phase14.relationships import digest

RESEARCH_POLICIES = {
    "high_throughput": {"tier": "standard", "target_notional": 2., "minimum_edge": .03,
                        "maximum_interval_width": .35, "minimum_support_groups": 2},
    "high_conviction": {"tier": "high", "target_notional": 5., "minimum_edge": .05,
                        "maximum_interval_width": .15, "minimum_support_groups": 2},
}


def _dict(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value if isinstance(value, dict) else {}


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("aware_timestamp_required")
    return at.astimezone(UTC)


def _number(value, *, low=0, high=float("inf")):
    return type(value) in (float, int) and isfinite(value) and low <= value <= high


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _verified(context, name, *args):
    try:
        return callable(context.get(name)) and context[name](*args) is True
    except Exception:  # noqa: BLE001 - verification errors never qualify a proposal
        return False


def _independent_support(evidence, forecast, context):
    """Provider names never substitute for reviewed shared-upstream dependencies."""
    groups, upstream, ids = [], set(), set()
    reasons = []
    if not isinstance(evidence, (list, tuple)) or len(evidence) > 32:
        return [], ["bounded_independent_evidence_required"]
    for raw in evidence:
        e = _dict(raw)
        try:
            if len(str(e)) > 262144 or any(not isinstance(e.get(k), str) or not 1 <= len(e[k]) <= 256
                for k in ("id", "provider", "source_id", "domain")):
                raise ValueError("bounded_support_identity_and_payload_required")
            identity = e["id"]
            if identity in ids:
                raise ValueError("duplicate_support_evidence")
            ids.add(identity)
            if (e.get("independent_of_polymarket") is not True or e.get("qualification") != "qualified_research"
                or not _hash(e.get("content_sha256")) or digest(e.get("payload")) != e["content_sha256"]):
                raise ValueError("qualified_independent_raw_evidence_required")
            parsed = urlsplit(e["source"])
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.hostname == "polymarket.com" or parsed.hostname.endswith(".polymarket.com")):
                raise ValueError("independent_external_source_required")
            retrieved, available, cutoff = map(_at, (e["retrieved_at"], e["available_at"], forecast["evidence_cutoff"]))
            if not retrieved <= available <= cutoff or _at(e["timestamp"]) > available:
                raise ValueError("support_not_available_at_forecast_cutoff")
            if e.get("source_timestamp") is not None and _at(e["source_timestamp"]) > retrieved:
                raise ValueError("future_support_publication")
            payload = e["payload"]
            if payload.get("supported_event_id") != forecast.get("event_id"):
                raise ValueError("support_event_relevance_unverified")
            lineage = payload.get("independence", {})
            group, sources = lineage.get("source_group"), lineage.get("upstream_groups")
            if (lineage.get("reviewed") is not True or not _hash(lineage.get("proof_sha256"))
                or not isinstance(group, str) or not 1 <= len(group) <= 128
                or not isinstance(sources, list) or not 1 <= len(sources) <= 32
                or any(not isinstance(s, str) or not 1 <= len(s) <= 128 for s in sources)):
                raise ValueError("reviewed_evidence_dependency_proof_required")
            if group in groups or upstream.intersection(sources):
                raise ValueError("correlated_or_shared_upstream_confirmation")
            if not _verified(context, "verify_evidence", e):
                raise ValueError("independent_raw_support_replay_required")
            groups.append(group)
            upstream.update(sources)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
            reasons.append(str(error)[:120])
    if len(groups) < 2:
        reasons.append("two_genuinely_independent_support_groups_required")
    if not _verified(context, "verify_independence", tuple(_dict(e) for e in evidence)):
        reasons.append("independent_dependency_review_required")
    return groups, reasons


def qualify_convergence(forecast, market, book, evidence, *, now, risk_context=None):
    """A negative-only research assessment; no record can authorize an order.

    Callbacks replay external evidence/rules/approval objects. Self-asserted source
    names, confidence, booleans or calibration labels are insufficient. Even a
    fully qualifying controlled case remains a research proposal requiring the
    unchanged operational account/risk/admission path at actual order time.
    """
    now, f, context = _at(now), _dict(forecast), risk_context if isinstance(risk_context, dict) else {}
    reasons, checks = [], {}
    base = {"schema_version": "phase18-convergence-v1", "evaluated_at": now.isoformat(),
        "research_qualified": False, "eligible": False, "trading_authority": False,
        "certification_authority": False, "risk_evaluated": False, "order_attempted": False,
        "forecast_id": f.get("id"), "estimated_net_edge": None, "qualified_net_edge": None,
        "actual_fill": False, "account_pnl": None, "approaches": {}, "reasons": reasons,
        "independent_support_groups": [], "checks": checks,
        "policy_sha256": digest(RESEARCH_POLICIES)}
    try:
        m = MarketSnapshot.model_validate(_dict(market))
        b = OrderBookSnapshot.model_validate(_dict(book)) if book is not None else None
        base.update(market_id=m.market_id, token_id=m.token_id, event_id=m.event_id,
            rules_sha256=sha256(m.resolution_rules.encode()).hexdigest(),
            book_id=b.id if b else None, book_sha256=digest(b.model_dump(mode="json")) if b else None,
            end_time=m.end_time.isoformat() if m.end_time else None, min_order_size=m.min_order_size, tick_size=m.tick_size)
        if (not isinstance(f.get("id"), str) or not 1 <= len(f["id"]) <= 256
            or any(not isinstance(f.get(k), str) or not 1 <= len(f[k]) <= 256 for k in ("model_version", "feature_version"))
            or any(not _hash(f.get(k)) for k in ("model_sha256", "dataset_sha256"))):
            reasons.append("versioned_forecast_model_dataset_provenance_required")
        identities = tuple(f.get(k) for k in ("event_id", "market_id", "token_id"))
        if identities != (m.event_id, m.market_id, m.token_id):
            reasons.append("forecast_market_identity_mismatch")
        if (m.status != "active" or m.source != "https://gamma-api.polymarket.com"
            or m.timestamp > now or m.available_at > now or (now-m.available_at).total_seconds() > 3600):
            reasons.append("fresh_active_authentic_market_required")
        if not m.end_time or m.end_time <= now:
            reasons.append("verified_future_resolution_horizon_required")
        if (not m.resolution_rules or not m.resolution_source or f.get("rules_sha256") != base["rules_sha256"]
            or not _verified(context, "verify_rules", f, m.model_dump(mode="json"))):
            reasons.append("exact_resolution_rule_proof_required")
        if (f.get("probability_semantics") != "binary_event_probability"
            or f.get("independent_of_polymarket") is not True):
            reasons.append("independent_binary_event_probability_required")
        uncertainty = f.get("uncertainty") if isinstance(f.get("uncertainty"), dict) else {}
        p = f.get("probability")
        lower, upper = (f.get("lower_probability", uncertainty.get("lower_probability")),
                        f.get("upper_probability", uncertainty.get("upper_probability")))
        interval = all(_number(v, high=1) for v in (p, lower, upper)) and lower <= p <= upper
        if not interval or upper-lower > .35:
            reasons.append("qualified_bounded_forecast_uncertainty_required")
        if f.get("calibration_status") != "independently_validated" or not _verified(context, "verify_forecast", f):
            reasons.append("independently_replayed_calibration_and_model_required")
        at, available, cutoff = map(_at, (f["timestamp"], f["available_at"], f["evidence_cutoff"]))
        if not cutoff <= at <= available <= now or (now-at).total_seconds() > 300:
            reasons.append("fresh_causal_forecast_required")
        groups, support_reasons = _independent_support(evidence, f, context)
        base["independent_support_groups"] = groups
        reasons.extend(support_reasons)
        if set(f.get("evidence_ids", [])) != {_dict(e).get("id") for e in evidence}:
            reasons.append("forecast_support_identity_binding_required")
        if f.get("relationship_used") is True and not _verified(context, "verify_persistent_relationship", f):
            reasons.append("persistent_qualified_relationship_proof_required")
        if b and (len(b.asks) > 1000 or len(b.bids) > 1000
            or len({p.price for p in b.asks}) != len(b.asks) or len({p.price for p in b.bids}) != len(b.bids)):
            reasons.append("bounded_unique_order_book_levels_required")
        health = assess_book(b, now, expected_token=m.token_id, max_spread=.05)
        reasons.extend(health.reasons)
        if b and (b.market_id != m.market_id or b.source not in PUBLIC_BOOK_SOURCES or b.exchange != "polymarket"
                  or not 0 <= (now-b.available_at).total_seconds() <= 15):
            reasons.append("authentic_current_book_identity_required")
        fee = verified_fee_rate(context.get("fee_observation", {}), now)
        if fee is None or not _verified(context, "verify_fee", context.get("fee_observation", {}), m.model_dump(mode="json")):
            reasons.append("verified_current_fee_required")
            fee = None
        if not (context.get("paper_trading") is True and context.get("live_trading_enabled") is False):
            reasons.append("explicit_paper_only_context_required")
        if context.get("emergency_stop") is not False:
            reasons.append("clear_verified_stop_state_required")
        if not (context.get("experimental_admission_authorized") is True
                and context.get("terminal_execution_authorized") is True
                and _verified(context, "verify_admission", f)):
            reasons.append("existing_explicit_strategy_and_execution_admission_required")
        if context.get("risk_approved") is not True or not _verified(context, "verify_risk", f, _dict(market), _dict(book)):
            reasons.append("explicit_existing_risk_approval_required")
        if interval and b and b.asks and fee is not None:
            base["estimated_net_edge"] = lower*(1-fee)-b.asks[0].price*(1+fee)-.02
            base.update(probability=p, lower_probability=lower, upper_probability=upper, fee_rate=fee,
                        slippage_per_leg=.01, liquidity_participation=.1)
            if base["estimated_net_edge"] < .03:
                reasons.append("uncertainty_cost_adjusted_edge_below_existing_floor")
        limits = ("remaining_aggregate_notional", "remaining_market_notional", "remaining_event_notional", "remaining_correlation_notional", "cash")
        if any(not _number(context.get(k)) for k in limits):
            reasons.append("current_correlation_event_capital_headroom_required")
        bankroll = context.get("initial_bankroll")
        if bankroll != 500 or isinstance(bankroll, bool) or context.get("aggregate_exposure_fraction") != .2:
            reasons.append("unchanged_bankroll_and20percent_exposure_policy_required")
        checks.update(independent_event_probability=interval and f.get("independent_of_polymarket") is True,
            source_groups=len(groups), book_healthy=health.healthy, calibration_replayed=
                f.get("calibration_status") == "independently_validated" and _verified(context, "verify_forecast", f))
        for name, policy in RESEARCH_POLICIES.items():
            policy_reasons = list(reasons)
            edge = base["estimated_net_edge"]
            if edge is None or edge < policy["minimum_edge"]:
                policy_reasons.append("research_policy_edge_requirement")
            if not interval or upper-lower > policy["maximum_interval_width"]:
                policy_reasons.append("research_policy_uncertainty_requirement")
            principal = quantity = cash = None
            if b and b.asks:
                quantity = max(m.min_order_size, policy["target_notional"]/b.asks[0].price)
                principal = quantity*b.asks[0].price
                cap = 5 if policy["tier"] == "standard" else 15
                if principal > cap+1e-9 or quantity > b.asks[0].size*.1+1e-9:
                    policy_reasons.append("existing_position_tier_or_best_limit_depth_cap")
                cash = principal*(1+fee) if fee is not None else None
                if cash is None or any(not _number(context.get(k)) or cash > context[k]+1e-9 for k in limits):
                    policy_reasons.append("portfolio_event_correlation_or_cash_headroom")
                proposal = {"tier": policy["tier"], "quantity": quantity, "principal": principal,
                            "fee_inclusive_notional": cash, "book_id": b.id, "market_id": m.market_id,
                            "token_id": m.token_id}
                if (not _number(context.get("approved_notional")) or cash is None
                    or cash > context["approved_notional"]+1e-9
                    or not _verified(context, "verify_proposal", f, name, proposal)):
                    policy_reasons.append("amount_bound_existing_risk_proposal_approval_required")
                if _number(bankroll, low=1) and cash is not None and cash > .2*bankroll+1e-9:
                    policy_reasons.append("aggregate20percent_exposure_cap")
            base["approaches"][name] = {"research_qualified": not policy_reasons,
                "proposed_notional": principal if not policy_reasons else None,
                "proposed_quantity": quantity if not policy_reasons else None,
                "fee_inclusive_reservation": cash if not policy_reasons else None,
                "tier": policy["tier"], "reasons": sorted(set(policy_reasons)),
                "hypothetical_proposal_only": True, "trading_authority": False}
        base["research_qualified"] = any(p["research_qualified"] for p in base["approaches"].values())
        if base["research_qualified"]:
            base["qualified_net_edge"] = base["estimated_net_edge"]
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
        reasons.append("invalid_convergence_inputs:"+str(error)[:120])
    for name, policy in RESEARCH_POLICIES.items():
        if name not in base["approaches"]:
            base["approaches"][name] = {"research_qualified": False, "proposed_notional": None,
                "proposed_quantity": None, "fee_inclusive_reservation": None, "tier": policy["tier"],
                "reasons": sorted(set(reasons)), "hypothetical_proposal_only": True, "trading_authority": False}
    base["reasons"] = sorted(set(reasons))
    base["cost_semantics"] = "Conservative two-leg notional fee bound plus .01/share slippage per leg; not exact settlement fees"
    base["limitations"] = ["No callback, evidence or result grants an order or certification authority",
        "Different providers can share upstream data or latent event drivers; independence requires separate proof",
        "A currently displayed quote cannot guarantee a future fill or price after latency",
        "Research policy comparisons share one market and liquidity; they are not independent accounts",
        "Exceptional15–25tiers are not proposed without a separately implemented exceptional approval package"]
    return base
