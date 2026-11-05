"""Relationship changes support investigation; they are never a profit claim.

The frozen training window contains only observations available before the tested
observation. Persisted observation IDs and stable evidence IDs permit replay.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from itertools import pairwise
from math import isfinite, sqrt
from statistics import mean, pstdev

from neraium_poly.contracts import MarketRelationship, MarketSnapshot, RelationshipEvidence


def _identity(*parts: object) -> str:
    return sha256(repr(parts).encode()).hexdigest()


def _aware(now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("timezone required")


@dataclass(frozen=True)
class RelationshipPolicy:
    baseline_size: int = 20
    persistence_required: int = 3
    z_threshold: float = 3.0
    minimum_shift: float = 0.03
    noise_floor: float = 0.01
    minimum_relationship_confidence: float = 0.7
    max_age_seconds: float = 60.0
    max_skew_seconds: float = 15.0
    max_gap_seconds: float = 120.0
    logical_tolerance: float = 0.02
    max_relationships: int = 1000

    def __post_init__(self):
        if self.baseline_size < 3 or self.persistence_required < 2 or self.max_relationships < 1:
            raise ValueError("insufficient temporal evidence policy")
        for name in (
            "z_threshold",
            "minimum_shift",
            "noise_floor",
            "max_age_seconds",
            "max_skew_seconds",
            "max_gap_seconds",
            "logical_tolerance",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"invalid {name}")
        if not 0 <= self.minimum_relationship_confidence <= 1:
            raise ValueError("invalid confidence policy")


@dataclass(frozen=True)
class EvidenceContext:
    """Explicit research context, never inferred from relationship confidence."""

    complete: bool = True
    liquidity_usd: float = 100.0
    spread: float = 0.02
    minimum_liquidity_usd: float = 20.0
    maximum_spread: float = 0.1
    settlement_reviewed: bool = False
    source: str = "research-context"

    def __post_init__(self):
        for name in ("liquidity_usd", "spread", "minimum_liquidity_usd", "maximum_spread"):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"invalid {name}")
        if not self.source:
            raise ValueError("context source required")


class RelationshipGraph:
    """Explicit ontology; logical edges require reviewed settlement semantics."""

    def __init__(self):
        self._edges: dict[str, MarketRelationship] = {}

    def add(self, edge: MarketRelationship) -> None:
        if len(edge.market_ids) < 2 or len(set(edge.market_ids)) != len(edge.market_ids):
            raise ValueError("at least two distinct markets required")
        if edge.kind in {"statistical", "conditional", "implication"} and len(edge.market_ids) != 2:
            raise ValueError("directed and statistical edges require two markets")
        previous = self._edges.get(edge.id)
        if previous is not None and previous != edge:
            raise ValueError("relationship ID collision; version changes need a new ID")
        self._edges[edge.id] = edge

    def neighbors(self, market_id: str) -> tuple[MarketRelationship, ...]:
        return tuple(edge for edge in self._edges.values() if market_id in edge.market_ids)

    def edges(self) -> tuple[MarketRelationship, ...]:
        return tuple(self._edges.values())


@dataclass
class _State:
    definition: MarketRelationship
    baseline: list[float] = field(default_factory=list)
    baseline_ids: list[str] = field(default_factory=list)
    run_ids: deque[tuple[str, ...]] = field(default_factory=deque)
    run_count: int = 0
    direction: int = 0
    last_at: datetime | None = None
    last_pair: tuple[str, ...] | None = None
    last_evidence: RelationshipEvidence | None = None
    samples: int = 0


class RelationshipEngine:
    """Observe in availability order; duplicates do not inflate persistence.

    ``observe`` always returns evidence, including explicit suppression reasons.
    Statistical residual shifts are qualified findings, not pricing constraints.
    Logical constraints require a reviewed rule and context settlement review.
    """

    def __init__(self, policy: RelationshipPolicy | None = None):
        self.policy = policy or RelationshipPolicy()
        self.graph = RelationshipGraph()
        self._states: dict[str, _State] = {}

    def observe(
        self,
        relationship: MarketRelationship,
        snapshots: Mapping[str, MarketSnapshot],
        now: datetime,
        context: EvidenceContext | None = None,
    ) -> RelationshipEvidence:
        _aware(now)
        context_missing = context is None
        context = context or EvidenceContext()
        if relationship.id not in self._states and len(self._states) >= self.policy.max_relationships:
            raise ValueError("relationship capacity reached")
        self.graph.add(relationship)
        if relationship.id not in self._states:
            if len(self._states) >= self.policy.max_relationships:
                raise ValueError("relationship capacity reached")
            self._states[relationship.id] = _State(definition=relationship)
        state = self._states[relationship.id]
        reasons: list[str] = ["missing_context"] if context_missing else []
        if relationship.available_at > now:
            reasons.append("relationship_not_available")
        if relationship.confidence < self.policy.minimum_relationship_confidence:
            reasons.append("relationship_confidence_insufficient")
        markets = [snapshots.get(mid) for mid in relationship.market_ids]
        if any(m is None for m in markets):
            reasons.append("missing_market_data")
        usable = [m for m in markets if m is not None]
        if any(m.market_id != mid for mid, m in zip(relationship.market_ids, markets) if m):
            reasons.append("market_identity_mismatch")
        if any(m.available_at > now or m.timestamp > now for m in usable):
            reasons.append("future_data")
        if any((now - m.timestamp).total_seconds() > self.policy.max_age_seconds for m in usable):
            reasons.append("stale_market_data")
        if (
            usable
            and (max(m.timestamp for m in usable) - min(m.timestamp for m in usable)).total_seconds()
            > self.policy.max_skew_seconds
        ):
            reasons.append("unaligned_market_data")
        if any(m.status != "active" for m in usable):
            reasons.append("market_not_active")
        if any(not m.resolution_rules or not m.resolution_source for m in usable):
            reasons.append("missing_resolution_semantics")
        if not context.complete:
            reasons.append("incomplete_context")
        if context.liquidity_usd < context.minimum_liquidity_usd:
            reasons.append("illiquid_context")
        if context.spread > context.maximum_spread:
            reasons.append("wide_spread_context")
        logical = relationship.kind != "statistical"
        if logical and (
            not relationship.rule_verified
            or not relationship.rule_description
            or not context.settlement_reviewed
        ):
            reasons.append("unverified_settlement_constraint")
        if relationship.kind == "conditional":
            reasons.append("conditional_joint_probability_required")
        pair = tuple(m.id for m in usable)
        # Reusing either leg cannot count as a fresh paired observation.
        if state.last_pair and set(pair) & set(state.last_pair):
            if pair == state.last_pair and not reasons and state.last_evidence is not None:
                return state.last_evidence
            reasons.append("reused_observation")
        if state.last_at is not None and any(m.available_at <= state.last_at for m in usable):
            reasons.append("out_of_order_observation")
        if reasons:
            state.run_count = 0
            state.run_ids.clear()
            state.direction = 0
            return self._evidence(relationship, state, now, context, reasons, 0, "unqualified", pair)
        values = [m.probability for m in usable]
        if relationship.kind == "statistical":
            residual = values[0] - values[1]
        elif relationship.kind == "implication":
            residual = max(0.0, values[0] - values[1])
        elif relationship.kind == "mutually_exclusive":
            residual = max(0.0, sum(values) - 1.0)
        else:  # exhaustive means both exclusive and exhaustive, independently reviewed
            residual = sum(values) - 1.0
        state.samples += 1
        state.last_pair = pair
        at = max(m.available_at for m in usable)
        if state.last_at is not None and (at - state.last_at).total_seconds() > self.policy.max_gap_seconds:
            state.run_count = 0
            state.run_ids.clear()
            state.direction = 0
        state.last_at = at
        if len(state.baseline) < self.policy.baseline_size:
            state.baseline.append(residual)
            state.baseline_ids.extend(pair)
            return self._evidence(
                relationship, state, now, context, ["insufficient_baseline"], 0, "learning", pair
            )
        baseline_mean = mean(state.baseline)
        baseline_scale = max(pstdev(state.baseline), self.policy.noise_floor)
        departure = residual - baseline_mean if not logical else residual
        strength = abs(departure) / baseline_scale
        changed = abs(departure) >= self.policy.minimum_shift and strength >= self.policy.z_threshold
        if logical:
            changed = abs(residual) > self.policy.logical_tolerance
        direction = 1 if departure > 0 else -1
        if changed and (state.direction == 0 or state.direction == direction):
            state.run_count += 1
            state.run_ids.append(pair)
            while len(state.run_ids) > self.policy.persistence_required:
                state.run_ids.popleft()
        elif changed:
            state.run_count = 1
            state.run_ids.clear()
            state.run_ids.append(pair)
        else:
            state.run_count = 0
            state.run_ids.clear()
        state.direction = direction if changed else 0
        if not changed:
            reasons.append("no_material_relationship_change" if not logical else "constraint_satisfied")
        elif state.run_count < self.policy.persistence_required:
            reasons.append("insufficient_persistence")
        regime = "constraint_inconsistency" if logical else "persistent_relationship_shift"
        if not changed:
            regime = "stable"
        if pstdev(state.baseline) > 0.15:
            regime = "volatile_baseline"
            reasons.append("volatile_relationship_baseline")
        return self._evidence(relationship, state, now, context, reasons, strength, regime, pair)

    def _evidence(self, relationship, state, now, context, reasons, strength, regime, pair):
        qualified = not reasons
        confidence = min(relationship.confidence, len(state.baseline) / self.policy.baseline_size)
        confidence *= min(1.0, state.run_count / self.policy.persistence_required)
        evidence = RelationshipEvidence(
            id=_identity(
                relationship.model_dump_json(), pair, now.isoformat(), context, self.policy, tuple(reasons)
            ),
            timestamp=now,
            available_at=now,
            source=f"relationship-engine/v1:{context.source}",
            relationship_id=relationship.id,
            sample_count=state.samples,
            persistence=state.run_count,
            strength=strength,
            confidence=confidence,
            qualified=qualified,
            reasons=tuple(reasons),
            observation_ids=tuple(state.baseline_ids)
            + tuple(item for observation in state.run_ids for item in observation),
            regime=regime,
        )
        state.last_evidence = evidence
        return evidence


def discover_statistical_relationship(
    left: Sequence[MarketSnapshot],
    right: Sequence[MarketSnapshot],
    now: datetime,
    minimum_samples: int = 20,
    minimum_correlation: float = 0.7,
) -> MarketRelationship | None:
    """Conservative synchronous Pearson discovery over past probability changes.

    Levels are intentionally not correlated: trending probability levels produce
    spurious high correlations. Discovery is statistical, never a settlement rule.
    """
    _aware(now)
    if minimum_samples < 3 or not 0 <= minimum_correlation <= 1:
        raise ValueError("invalid discovery policy")

    def eligible(series):
        result = {}
        for item in series:
            if item.available_at <= now and item.timestamp <= now and item.status == "active":
                if item.timestamp in result:
                    raise ValueError("duplicate event timestamp; select a causal revision first")
                result[item.timestamp] = item
        return result

    ls, rs = eligible(left), eligible(right)
    times = sorted(ls.keys() & rs.keys())
    if len(times) < minimum_samples + 1:
        return None
    lmarkets = {ls[t].market_id for t in times}
    rmarkets = {rs[t].market_id for t in times}
    if len(lmarkets) != 1 or len(rmarkets) != 1 or lmarkets == rmarkets:
        raise ValueError("discovery requires distinct single-market series")
    x = [ls[b].probability - ls[a].probability for a, b in pairwise(times)]
    y = [rs[b].probability - rs[a].probability for a, b in pairwise(times)]
    mx, my = mean(x), mean(y)
    denom = sqrt(sum((v - mx) ** 2 for v in x) * sum((v - my) ** 2 for v in y))
    if denom <= 1e-15:
        return None
    correlation = sum((a - mx) * (b - my) for a, b in zip(x, y)) / denom
    if abs(correlation) < minimum_correlation:
        return None
    ids = tuple(v.id for t in times for v in (ls[t], rs[t]))
    return MarketRelationship(
        id=_identity("statistical-discovery-v1", ids),
        timestamp=now,
        available_at=now,
        source="statistical-discovery/v1",
        market_ids=(next(iter(lmarkets)), next(iter(rmarkets))),
        kind="statistical",
        confidence=min(0.99, abs(correlation)),
        rule_verified=False,
        rule_description=f"Past probability-change Pearson r={correlation:.6f}; not a logical constraint",
    )
