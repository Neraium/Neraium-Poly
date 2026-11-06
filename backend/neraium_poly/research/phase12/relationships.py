"""Event relation layers: statistical evidence, reviewed logic, causality, execution."""

import hashlib
from collections import Counter
from datetime import datetime
from math import isfinite

from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES, verified_fee_rate
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.intelligence import ExperimentalRelationshipIntelligence
from neraium_poly.research.phase11.contracts import ExperimentSpec
from neraium_poly.research.phase12.models import _parse


class EventRelationshipEngine:
    """Persistent temporal descriptive engine; no order or certification authority."""

    def __init__(self, max_relationships=200):
        if not 1 <= max_relationships <= 200:
            raise ValueError("bounded event relationship capacity required")
        self.intelligence = ExperimentalRelationshipIntelligence(max_relationships=max_relationships)
        self.cycles = 0
        self.evaluations = 0
        self.last_evaluation_at = None

    def observe(self, frame, now):
        if now.tzinfo is None:
            raise ValueError("aware event relationship time required")
        frame = frame if isinstance(frame, SharedMarketFrame) else SharedMarketFrame.model_validate(frame)
        if (
            frame.timestamp > now
            or frame.available_at > now
            or (now - frame.available_at).total_seconds() > 15
            or frame.producer_health.get("status") != "ok"
        ):
            return {
                "status": "withheld",
                "reason": "fresh_healthy_public_frame_required",
                "executable_opportunities": 0,
            }
        if len(frame.markets) > 400 or len({m.token_id for m in frame.markets}) != len(frame.markets):
            raise ValueError("bounded unambiguous event universe required")
        if len(frame.books) > 400 or len({b.token_id for b in frame.books}) != len(frame.books):
            raise ValueError("bounded unambiguous event books required")
        if any(b.source not in PUBLIC_BOOK_SOURCES or b.exchange != "polymarket" for b in frame.books):
            raise ValueError("authentic public event books required")
        markets = {m.token_id: m for m in frame.markets}
        books = {b.token_id: b for b in frame.books}
        findings = self.intelligence.observe(markets, books, now)
        self.cycles += 1
        self.evaluations += len(findings)
        self.last_evaluation_at = now.isoformat()
        result = self.intelligence.status()
        return {
            **result,
            "status": "descriptive_only",
            "cycles": self.cycles,
            "cumulative_relationship_evaluations": self.evaluations,
            "last_evaluation_at": self.last_evaluation_at,
            "statistical_findings": sum(f.qualified for f in findings),
            "logical_constraints_verified": 0,
            "causal_hypotheses_verified": 0,
            "executable_opportunities": 0,
            "classification": "Same-event dependency priors and qualified temporal shifts do not establish causal influence, logical payoff identity or executable profit",
            "certification_authority": False,
            "automatic_promotion": False,
        }

    def checkpoint(self):
        return {
            "schema_version": "1.0",
            "intelligence": self.intelligence.checkpoint(),
            "cycles": self.cycles,
            "evaluations": self.evaluations,
            "last_evaluation_at": self.last_evaluation_at,
        }

    def restore(self, data):
        if data.get("schema_version") != "1.0" or any(
            type(data.get(k)) is not int or data[k] < 0 for k in ("cycles", "evaluations")
        ):
            raise ValueError("invalid event relationship checkpoint")
        self.intelligence.restore(data["intelligence"])
        self.cycles = data["cycles"]
        self.evaluations = data["evaluations"]
        self.last_evaluation_at = data.get("last_evaluation_at")
        if (
            self.last_evaluation_at is not None
            and datetime.fromisoformat(self.last_evaluation_at).tzinfo is None
        ):
            raise ValueError("aware persisted event time required")


def evaluate_logical_constraint(constraint, frame, now, *, quantity=5, slippage_per_share=0.01):
    """Review-bound quote arithmetic, explicitly NOT an executable multi-leg order.

    Positive discrepancy remains theoretical until a separately authorized
    execution adapter can coordinate all legs, latency, settlement and capital.
    """
    if (
        now.tzinfo is None
        or not isfinite(quantity)
        or quantity <= 0
        or not isfinite(slippage_per_share)
        or slippage_per_share < 0
    ):
        raise ValueError("bounded logical research inputs required")
    frame = frame if isinstance(frame, SharedMarketFrame) else SharedMarketFrame.model_validate(frame)
    reasons = []
    kind = constraint.get("kind")
    tokens = constraint.get("token_ids", [])
    if (
        kind not in ("exhaustive", "mutually_exclusive", "implication")
        or len(tokens) < 2
        or len(tokens) > 20
        or len(tokens) != len(set(tokens))
    ):
        return {
            "relationship_layer": "unqualified_relation",
            "kind": kind,
            "reasons": ["unsupported_constraint_scope"],
            "quote_level_net_difference": None,
            "positive_reviewed_quote_discrepancy": False,
            "executable_opportunity": False,
            "execution_blocker": "Unsupported scope",
            "certification_authority": False,
            "automatic_promotion": False,
        }
    try:
        reviewed = datetime.fromisoformat(constraint.get("reviewed_at", ""))
        if reviewed.tzinfo is None or reviewed > now:
            raise ValueError
    except (ValueError, TypeError):
        reasons.append("predecision_constraint_review_required")
    if (
        not constraint.get("review_actor")
        or not constraint.get("payoff_scope_verified")
        or not constraint.get("settlement_compatible")
        or not constraint.get("review_evidence_ids")
    ):
        reasons.append("independent_payoff_and_settlement_review_required")
    markets = {m.token_id: m for m in frame.markets}
    books = {b.token_id: b for b in frame.books}
    selected = []
    fees = []
    if frame.producer_health.get("status") != "ok" or frame.timestamp > now or frame.available_at > now:
        reasons.append("fresh_healthy_public_frame_required")
    for token in tokens:
        market = markets.get(token)
        book = books.get(token)
        if (
            market is None
            or book is None
            or book.source not in PUBLIC_BOOK_SOURCES
            or book.exchange != "polymarket"
            or not assess_book(book, now, expected_token=token, max_spread=0.05).healthy
        ):
            reasons.append("fresh_complete_executable_book_required")
            continue
        if (
            market.market_id != book.market_id
            or market.exchange != book.exchange
            or market.available_at > now
            or market.timestamp > now
            or market.status != "active"
            or (market.end_time is not None and market.end_time <= now)
            or not market.resolution_rules
            or not market.resolution_source
        ):
            reasons.append("active_identity_matched_rule_context_required")
        if (
            constraint.get("rule_hashes", {}).get(token)
            != hashlib.sha256(market.resolution_rules.encode()).hexdigest()
        ):
            reasons.append("reviewed_rule_hash_mismatch")
        fee = verified_fee_rate(frame.fees.get(token, {}), now)
        if fee is None:
            reasons.append("verified_current_fee_required")
        else:
            fees.append(fee)
        if book.asks[0].size * 0.1 < quantity or market.min_order_size > quantity:
            reasons.append("insufficient_atomic_bundle_depth_or_minimum_lot")
        selected.append(book)
    if (
        selected
        and (max(b.timestamp for b in selected) - min(b.timestamp for b in selected)).total_seconds() > 2
    ):
        reasons.append("unaligned_bundle_source_times")
    quoted_edge = None
    if not reasons and kind == "exhaustive":
        cost = sum(
            quantity * (b.asks[0].price * (1 + fee) + slippage_per_share)
            for b, fee in zip(selected, fees, strict=True)
        )
        quoted_edge = quantity - cost
    elif not reasons:
        reasons.append("sell_or_conditional_hedging_not_supported")
    return {
        "relationship_layer": "logically_reviewed_quote_research" if not reasons else "unqualified_relation",
        "kind": kind,
        "reasons": sorted(set(reasons)),
        "quote_level_net_difference": quoted_edge,
        "positive_reviewed_quote_discrepancy": quoted_edge is not None and quoted_edge > 1e-8,
        "executable_opportunity": False,
        "execution_blocker": "Multi-leg atomicity, latency and settlement-capital execution are unsupported",
        "certification_authority": False,
        "automatic_promotion": False,
    }


def run_event_relationships(dataset):
    manifest, events, evidence, outcomes = _parse(dataset)
    groups = Counter(x.dependency_group for x in events)
    price_rows = [e for e in evidence if e.kind == "market_price"]
    pit = [e for e in price_rows if e.available_at <= e.timestamp]
    digest = manifest.get("dataset_sha256") or hashlib.sha256(str(sorted(manifest)).encode()).hexdigest()
    spec = ExperimentSpec(
        experiment_id="phase12-event-relationship-v1",
        hypothesis="Persistent changes among related event probabilities may yield qualified structural evidence; reviewed logical payoff constraints require separate execution validation",
        dataset_sha256=digest,
        model_version="event-temporal-relationship-v1",
        feature_definitions={
            "statistical": "same reported event membership; actual synchronous fresh quote midpoints only",
            "logic": "independently reviewed payoff scope/rule hashes, never inferred from correlation",
        },
        target_definitions={
            "structural": "persistent contextual departure from temporal baseline, not profitable anomaly"
        },
        split_policy="Historical relationships only evaluated from genuinely available causal observations; live evidence uses persisted past-only baseline",
        grouping={
            "reported_dependency_groups": len(groups),
            "independently_reviewed": sum(e.independence_reviewed for e in events),
        },
        transaction_cost_assumptions={
            "execution": "Reviewed arithmetic needs actual bid/ask/depth/fees/timing; atomic multi-leg execution unsupported"
        },
        failure_conditions=(
            "Missing predecision observations",
            "Missing rule/payoff review",
            "Stale or asynchronous legs",
            "Unknown fees or depth",
            "Unsupported execution",
        ),
        limitations=(
            "Statistical dependence does not prove causation",
            "Logical discrepancy does not prove executable profit",
            "Collected-now historical prices cannot be backdated",
        ),
    )
    return {
        "spec": spec.model_dump(mode="json"),
        "canonical_events": len(events),
        "reported_dependency_groups": len(groups),
        "dependency_group_sizes": dict(groups),
        "historical_price_evidence": len(price_rows),
        "predecision_available_price_evidence": len(pit),
        "historical_depth_evidence": sum(e.kind == "order_book" for e in evidence),
        "verified_outcomes": len(outcomes),
        "logical_constraints_verified": 0,
        "causal_hypotheses_verified": 0,
        "persistent_findings": None if not pit else 0,
        "executable_opportunities": 0,
        "independent_false_positive_rate": None,
        "independent_confidence_interval": None,
        "reason": "Historical availability and reviewed logical/event context insufficient; live descriptive temporal engine remains separate",
        "classification_layers": [
            "observed_statistical_relationship",
            "reviewed_logical_constraint",
            "causal_hypothesis",
            "executable_opportunity",
        ],
        "certification_authority": False,
        "automatic_promotion": False,
    }
