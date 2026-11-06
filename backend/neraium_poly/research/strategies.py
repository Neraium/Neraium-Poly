"""Six research hypotheses. Signals are diagnostic records, never order authority."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import pairwise
from math import isfinite
from urllib.parse import urlparse

from neraium_poly.contracts import (
    MarketRelationship,
    OrderBookSnapshot,
    ProbabilityEstimate,
    RelationshipEvidence,
)
from neraium_poly.data import assess_book
from neraium_poly.research.contracts import ResearchContext


@dataclass(frozen=True)
class StrategySpec:
    id: str
    hypothesis: str
    universe: str
    entry: str
    exit: str
    value_model: str
    risk_assumptions: tuple[str, ...]
    failure_cases: tuple[str, ...]
    required_data: tuple[str, ...]


CATALOG = (
    StrategySpec(
        "persistent_relationship",
        "A persistent, contextual relationship change may improve a separately calibrated forecast.",
        "Reviewed related binary markets with causal baseline history",
        "Qualified persistent evidence plus calibrated lower-bound net value",
        "Reviewed resolution or independently validated forecast invalidation",
        "Independent lower probability minus executable ask, conservative fee and latency buffer",
        (
            "Statistical association is not a settlement equality",
            "Portfolio correlation caps and risk approval remain mandatory",
        ),
        ("Regime shift in calibrator", "Spurious association", "Unaligned or stale peers"),
        (
            "paired_causal_history",
            "persistent_qualified_evidence",
            "independent_calibrated_forecast",
            "executable_books",
            "known_fees",
        ),
    ),
    StrategySpec(
        "logical_constraints",
        "A verified exhaustive, exclusive payoff bundle can have cost below its minimum payout.",
        "Independently reviewed exhaustive and exclusive binary outcome bundles",
        "All-leg observed ask cost including fees and buffer below guaranteed reviewed payout",
        "Verified resolution of every leg",
        "Reviewed minimum bundle payout minus all-leg executable costs",
        (
            "Non-atomic leg fills can remove the locked-payoff property",
            "No shorting or token conversion is implemented",
        ),
        (
            "Different settlement definitions",
            "Missing outcome",
            "Partial bundle execution",
            "Resolution dispute",
        ),
        ("reviewed_logical_payoff", "all_leg_books", "known_fees", "atomic_or_hedged_leg_execution"),
    ),
    StrategySpec(
        "independent_forecast",
        "An external contemporaneous signal may outperform a market-price baseline after calibration.",
        "Binary markets with independently archived numeric or probability evidence",
        "Calibrated probability lower bound clears executable costs and uncertainty",
        "Reviewed resolution or validated evidence reversal",
        "Calibrated independent evidence probability minus executable costs",
        (
            "External context must have been available before decision",
            "Calibration must generalize out of sample",
        ),
        (
            "Revised source history",
            "Outcome leakage",
            "Poor probability calibration",
            "Missing independent provenance",
        ),
        (
            "independent_context",
            "event_independent_labels",
            "calibrated_forecast",
            "executable_books",
            "known_fees",
        ),
    ),
    StrategySpec(
        "liquidity_maker",
        "A spread may compensate conservative inventory and adverse-selection costs under a validated queue model.",
        "Two-sided liquid books with observable queue/trade history",
        "Non-crossing bid/ask quotes with validated fill probability and inventory budget",
        "Time-limited cancel, inventory cap, or observed liquidation",
        "Spread times supported fill probability minus fees, adverse selection and inventory costs",
        (
            "Displayed depth does not establish queue position",
            "Maker rebates are excluded",
            "No fabricated historical fills",
        ),
        ("Adverse selection", "Queue priority changes", "One-sided fills", "Unexecutable liquidation"),
        (
            "book_sequences",
            "queue_and_trade_history",
            "validated_fill_model",
            "inventory_exit_quotes",
            "known_fees",
        ),
    ),
    StrategySpec(
        "event_repricing",
        "A timestamped independent information update may precede incomplete market repricing.",
        "Markets with external event publication archives and fresh post-publication books",
        "Independent calibrated update with supported event timing and net edge",
        "Reviewed event resolution or evidence invalidation",
        "Calibrated updated probability minus fresh post-publication ask and costs",
        (
            "News event time and observed availability are separate",
            "Publication selection cannot use future price movement",
        ),
        (
            "Revised publication timestamp",
            "Duplicate news",
            "Already priced information",
            "Delayed executable quote",
        ),
        ("external_publication_archive", "pre_and_post_event_books", "calibrated_update", "known_fees"),
    ),
    StrategySpec(
        "microstructure",
        "Observed imbalance and quote persistence may predict a measured short-horizon return, separately from terminal outcome probability.",
        "Liquid markets with complete, ordered short-horizon depth and trades",
        "Validated horizon forecast and cost-adjusted return on fresh books",
        "Fixed research horizon using an actual observed exit bid",
        "Supported horizon return distribution minus entry/exit spread, fees and latency",
        (
            "Terminal probability is not a short-horizon up-move label",
            "Source gaps invalidate features",
            "Exit depth is required",
        ),
        ("Missing exit quote", "Timestamp gaps", "Latency reversals", "Uncalibrated imbalance heuristic"),
        (
            "ordered_book_sequences",
            "horizon_return_labels",
            "calibrated_horizon_forecast",
            "exit_depth",
            "known_fees",
        ),
    ),
)


@dataclass(frozen=True)
class ResearchSignal:
    strategy_id: str
    qualified: bool
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    estimated_probability: float | None = None
    conservative_probability: float | None = None
    expected_net_value: float | None = None
    proposed_bid: float | None = None
    proposed_ask: float | None = None
    diagnostic: float | None = None
    assumptions: tuple[str, ...] = ()
    activation_eligible: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def strategy_catalog() -> list[dict]:
    return [
        {key: list(value) if isinstance(value, tuple) else value for key, value in asdict(spec).items()}
        for spec in CATALOG
    ]


def _time(now: datetime):
    if now.tzinfo is None:
        raise ValueError("timezone required")


def _book_reasons(book: OrderBookSnapshot, now: datetime) -> list[str]:
    _time(now)
    return list(assess_book(book, now, max_age_seconds=15, max_spread=0.10).reasons)


def _context_reasons(context: ResearchContext, now: datetime) -> list[str]:
    _time(now)
    source = urlparse(context.source)
    reasons = []
    if (
        not context.independent
        or source.scheme != "https"
        or not source.hostname
        or source.hostname == "polymarket.com"
        or source.hostname.endswith(".polymarket.com")
        or not context.reference
        or len(context.raw_sha256) != 64
    ):
        reasons.append("independent_context_provenance_required")
    if context.timestamp > now or context.available_at > now:
        reasons.append("future_context")
    return reasons


def _forecast_signal(strategy_id, book, estimate, now, fee_rate, evidence_ids, reasons):
    reasons += _book_reasons(book, now)
    if fee_rate is None or not isfinite(fee_rate) or not 0 <= fee_rate <= 1:
        reasons.append("known_conservative_fee_bound_required")
    if estimate is None:
        reasons.append("independent_calibrated_forecast_required")
    else:
        if (estimate.market_id, estimate.token_id) != (book.market_id, book.token_id):
            reasons.append("forecast_instrument_mismatch")
        if estimate.available_at > now or estimate.timestamp > now:
            reasons.append("future_forecast")
        if (now - estimate.timestamp).total_seconds() > 300:
            reasons.append("stale_forecast")
        if not estimate.calibrated or estimate.upper - estimate.lower > 0.35:
            reasons.append("uncalibrated_or_uncertain_forecast")
        if set(evidence_ids) - set(estimate.evidence_ids):
            reasons.append("forecast_evidence_chain_mismatch")
    edge = None
    if (
        estimate is not None
        and book.asks
        and fee_rate is not None
        and isfinite(fee_rate)
        and 0 <= fee_rate <= 1
    ):
        edge = estimate.lower - book.asks[0].price * (1 + fee_rate) - 0.01
        if edge < 0.03:
            reasons.append("conservative_net_value_insufficient")
    return ResearchSignal(
        strategy_id,
        not reasons,
        tuple(sorted(set(reasons))),
        tuple(evidence_ids),
        estimate.probability if estimate else None,
        estimate.lower if estimate else None,
        edge,
        assumptions=(
            "Research qualification is not certification or owner approval",
            "BUY-only taker cost bound; no fill is created",
        ),
    )


def persistent_relationship_signal(
    evidence: RelationshipEvidence,
    book: OrderBookSnapshot,
    estimate: ProbabilityEstimate | None,
    now: datetime,
    fee_rate: float | None,
) -> ResearchSignal:
    reasons = []
    if (
        not evidence.qualified
        or evidence.confidence < 0.7
        or evidence.sample_count < 20
        or evidence.persistence < 3
        or not evidence.observation_ids
    ):
        reasons.append("persistent_qualified_relationship_evidence_required")
    if evidence.available_at > now or evidence.timestamp > now:
        reasons.append("future_relationship_evidence")
    if (now - evidence.timestamp).total_seconds() > 60:
        reasons.append("stale_relationship_evidence")
    if estimate is not None and evidence.available_at > estimate.available_at:
        reasons.append("noncausal_relationship_forecast")
    return _forecast_signal("persistent_relationship", book, estimate, now, fee_rate, (evidence.id,), reasons)


def logical_constraint_signal(
    relationship: MarketRelationship,
    books: Sequence[OrderBookSnapshot],
    now: datetime,
    fee_rates: dict[str, float],
    *,
    settlement_reviewed: bool = False,
    quantity: float = 1,
) -> ResearchSignal:
    _time(now)
    reasons = []
    if not relationship.rule_verified or not relationship.rule_description or not settlement_reviewed:
        reasons.append("reviewed_logical_payoff_required")
    if relationship.available_at > now:
        reasons.append("future_relationship")
    if relationship.kind != "exhaustive":
        reasons.append("buy_only_exhaustive_bundle_required")
    if relationship.kind == "statistical":
        reasons.append("correlation_is_not_logical_arbitrage")
    if (
        len(books) < 2
        or {b.market_id for b in books} != set(relationship.market_ids)
        or len({b.market_id for b in books}) != len(books)
        or len({b.token_id for b in books}) != len(books)
        or len({b.exchange for b in books}) != 1
    ):
        reasons.append("all_distinct_bundle_legs_required")
    if not isfinite(quantity) or quantity <= 0:
        reasons.append("invalid_quantity")
    costs = []
    for book in books:
        reasons += _book_reasons(book, now)
        rate = fee_rates.get(book.token_id)
        if rate is None or not isfinite(rate) or not 0 <= rate <= 1:
            reasons.append("known_all_leg_fees_required")
            continue
        if book.asks:
            if quantity > book.asks[0].size * 0.1:
                reasons.append("insufficient_conservative_leg_depth")
            costs.append(book.asks[0].price * (1 + rate))
    edge = 1 - sum(costs) - 0.01 * len(books) if len(costs) == len(books) and books else None
    if edge is not None and edge < 0.03:
        reasons.append("bundle_net_value_insufficient")
    return ResearchSignal(
        "logical_constraints",
        not reasons,
        tuple(sorted(set(reasons))),
        (relationship.id, *(b.id for b in books)),
        expected_net_value=edge,
        diagnostic=1 - sum(b.asks[0].price for b in books) if all(b.asks for b in books) and books else None,
        assumptions=(
            "Value is per complete bundle unit, not a forecast probability",
            "Non-atomic partial leg fills can remove guaranteed payout; no order authority",
        ),
    )


def independent_forecast_signal(
    context: ResearchContext,
    book: OrderBookSnapshot,
    estimate: ProbabilityEstimate | None,
    now: datetime,
    fee_rate: float | None,
) -> ResearchSignal:
    reasons = _context_reasons(context, now)
    if estimate is not None and context.available_at > estimate.available_at:
        reasons.append("noncausal_context_forecast")
    return _forecast_signal("independent_forecast", book, estimate, now, fee_rate, (context.id,), reasons)


def maker_signal(
    book: OrderBookSnapshot,
    now: datetime,
    *,
    tick: float = 0.01,
    maker_fee_rate: float | None = None,
    adverse_selection_bound: float | None = None,
    supported_fill_probability: float | None = None,
    queue_reference: str | None = None,
) -> ResearchSignal:
    reasons = _book_reasons(book, now)
    if not isfinite(tick) or tick <= 0:
        reasons.append("invalid_tick")
    bid = ask = edge = None
    if book.bids and book.asks and isfinite(tick) and tick > 0:
        bid = book.bids[0].price + tick
        ask = book.asks[0].price - tick
        if not 0 < bid < ask < 1:
            reasons.append("noncrossing_quote_space_required")
    if not queue_reference or supported_fill_probability is None:
        reasons.append("queue_position_and_fill_model_unvalidated")
    elif not isfinite(supported_fill_probability) or not 0 <= supported_fill_probability <= 1:
        reasons.append("invalid_fill_probability")
    if (
        maker_fee_rate is None
        or not isfinite(maker_fee_rate)
        or not 0 <= maker_fee_rate <= 1
        or adverse_selection_bound is None
        or not isfinite(adverse_selection_bound)
        or adverse_selection_bound < 0
    ):
        reasons.append("known_inventory_adverse_selection_and_fee_bounds_required")
    elif (
        bid is not None
        and ask is not None
        and supported_fill_probability is not None
        and isfinite(supported_fill_probability)
    ):
        edge = (
            (ask - bid) - (ask + bid) * maker_fee_rate - adverse_selection_bound
        ) * supported_fill_probability
        if edge < 0.03:
            reasons.append("maker_compensation_insufficient")
    return ResearchSignal(
        "liquidity_maker",
        not reasons,
        tuple(sorted(set(reasons))),
        (book.id,),
        expected_net_value=edge,
        proposed_bid=bid,
        proposed_ask=ask,
        assumptions=(
            "Conditional research quote; observed depth does not establish a fill",
            "Inventory liquidation and queue model require independent validation",
        ),
    )


def event_repricing_signal(
    context: ResearchContext,
    before: OrderBookSnapshot,
    after: OrderBookSnapshot,
    estimate: ProbabilityEstimate | None,
    now: datetime,
    fee_rate: float | None,
) -> ResearchSignal:
    reasons = _context_reasons(context, now)
    if (before.market_id, before.token_id, before.exchange) != (
        after.market_id,
        after.token_id,
        after.exchange,
    ):
        reasons.append("event_quote_identity_mismatch")
    if not (
        before.timestamp < context.timestamp <= context.available_at <= after.available_at <= now
        and before.timestamp < after.timestamp
    ):
        reasons.append("causal_pre_and_post_publication_quotes_required")
    return _forecast_signal(
        "event_repricing", after, estimate, now, fee_rate, (context.id, before.id, after.id), reasons
    )


def microstructure_signal(
    books: Sequence[OrderBookSnapshot],
    now: datetime,
    *,
    horizon_seconds: float = 60,
    calibrated_up_probability: float | None = None,
    horizon_validation_ref: str | None = None,
    mean_up_move: float | None = None,
    mean_down_move: float | None = None,
    round_trip_cost: float | None = None,
) -> ResearchSignal:
    _time(now)
    reasons = []
    if len(books) < 20:
        reasons.append("insufficient_ordered_microstructure_baseline")
    if not books:
        return ResearchSignal("microstructure", False, tuple(reasons))
    if len({(b.exchange, b.market_id, b.token_id) for b in books}) != 1:
        reasons.append("microstructure_instrument_mismatch")
    if any(not b.complete or not b.bids or not b.asks for b in books):
        reasons.append("incomplete_microstructure_history")
    if any(b.available_at > now for b in books):
        reasons.append("future_book")
    if any(
        right.timestamp <= left.timestamp
        or right.available_at <= left.available_at
        or (left.sequence > 0 and right.sequence > 0 and right.sequence != left.sequence + 1)
        for left, right in pairwise(books)
    ):
        reasons.append("unordered_or_gapped_source_books")
    reasons += _book_reasons(books[-1], now)
    if not isfinite(horizon_seconds) or horizon_seconds <= 0:
        reasons.append("invalid_horizon")
    if (
        calibrated_up_probability is None
        or not isfinite(calibrated_up_probability)
        or not 0 <= calibrated_up_probability <= 1
        or not horizon_validation_ref
    ):
        reasons.append("calibrated_horizon_forecast_required")
    values = (mean_up_move, mean_down_move, round_trip_cost)
    if any(v is None or not isfinite(v) or v < 0 for v in values):
        reasons.append("measured_horizon_returns_and_exit_cost_required")
    edge = None
    if not reasons:
        edge = (
            calibrated_up_probability * mean_up_move
            - (1 - calibrated_up_probability) * mean_down_move
            - round_trip_cost
        )
        if edge < 0.03:
            reasons.append("microstructure_net_value_insufficient")
    latest = books[-1]
    bids = sum(p.size for p in latest.bids[:3])
    asks = sum(p.size for p in latest.asks[:3])
    imbalance = (bids - asks) / (bids + asks) if bids + asks else None
    return ResearchSignal(
        "microstructure",
        not reasons,
        tuple(sorted(set(reasons))),
        tuple(b.id for b in books),
        estimated_probability=calibrated_up_probability,
        expected_net_value=edge,
        diagnostic=imbalance,
        assumptions=(
            "Probability concerns a fixed-horizon price move, not terminal resolution",
            "Imbalance alone is not calibrated probability; actual exit depth and labels are required",
        ),
    )
