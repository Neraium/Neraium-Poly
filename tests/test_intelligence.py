from datetime import timedelta

import pytest
from neraium_poly.contracts import MarketRelationship
from neraium_poly.intelligence import (
    EvidenceContext,
    RelationshipEngine,
    RelationshipGraph,
    RelationshipPolicy,
    discover_statistical_relationship,
)


def relation(now, kind="statistical", **kw):
    return MarketRelationship(
        id="rel",
        timestamp=now,
        available_at=now,
        source="fixture-review",
        market_ids=("m1", "m2"),
        kind=kind,
        confidence=0.95,
        **kw,
    )


def pair(market, now, i, difference=0):
    at = now + timedelta(seconds=i)
    a = market.model_copy(
        update={"id": f"a{i}", "timestamp": at, "available_at": at, "probability": 0.4 + difference}
    )
    b = market.model_copy(
        update={
            "id": f"b{i}",
            "market_id": "m2",
            "token_id": "t2",
            "timestamp": at,
            "available_at": at,
            "probability": 0.4,
        }
    )
    return {"m1": a, "m2": b}, at


def engine():
    return RelationshipEngine(RelationshipPolicy(baseline_size=3, persistence_required=2))


def train(e, r, market, now):
    for i in range(3):
        snapshots, at = pair(market, now, i)
        evidence = e.observe(r, snapshots, at, EvidenceContext())
        assert not evidence.qualified
        assert "insufficient_baseline" in evidence.reasons


def test_persistent_shift_qualifies_and_preserves_provenance(market, now):
    e, r = engine(), relation(now)
    train(e, r, market, now)
    snapshots, at = pair(market, now, 3, 0.15)
    first = e.observe(r, snapshots, at, EvidenceContext())
    assert not first.qualified and first.persistence == 1
    snapshots, at = pair(market, now, 4, 0.15)
    second = e.observe(r, snapshots, at, EvidenceContext())
    assert second.qualified and second.persistence == 2
    assert second.regime == "persistent_relationship_shift"
    assert len(second.observation_ids) == 10
    assert second.source == "relationship-engine/v1:research-context"
    assert second.confidence == 0.95


def test_single_excursion_and_reversing_shifts_suppressed(market, now):
    e, r = engine(), relation(now)
    train(e, r, market, now)
    for i, d in [(3, 0.15), (4, 0), (5, -0.15), (6, 0.15)]:
        snapshots, at = pair(market, now, i, d)
        evidence = e.observe(r, snapshots, at, EvidenceContext())
        assert not evidence.qualified
        assert evidence.persistence <= 1


def test_duplicate_does_not_inflate_persistence(market, now):
    e, r = engine(), relation(now)
    train(e, r, market, now)
    snapshots, at = pair(market, now, 3, 0.15)
    first = e.observe(r, snapshots, at, EvidenceContext())
    assert e.observe(r, snapshots, at, EvidenceContext()) == first
    assert e.observe(r, snapshots, at + timedelta(seconds=1), EvidenceContext()).persistence == 1


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("future", "future_data"),
        ("stale", "stale_market_data"),
        ("missing", "missing_market_data"),
        ("rules", "missing_resolution_semantics"),
        ("closed", "market_not_active"),
        ("skew", "unaligned_market_data"),
    ],
)
def test_data_quality_suppression(market, now, mode, reason):
    e, r = engine(), relation(now)
    snapshots, at = pair(market, now, 1)
    if mode == "future":
        at = now
    elif mode == "stale":
        at += timedelta(seconds=61)
    elif mode == "missing":
        snapshots.pop("m2")
    elif mode == "rules":
        snapshots["m1"] = snapshots["m1"].model_copy(update={"resolution_rules": ""})
    elif mode == "closed":
        snapshots["m1"] = snapshots["m1"].model_copy(update={"status": "closed"})
    elif mode == "skew":
        snapshots["m2"] = snapshots["m2"].model_copy(update={"timestamp": now - timedelta(seconds=20)})
    evidence = e.observe(r, snapshots, at, EvidenceContext())
    assert not evidence.qualified and reason in evidence.reasons
    assert evidence.sample_count == 0


@pytest.mark.parametrize(
    "context,reason",
    [
        (EvidenceContext(complete=False), "incomplete_context"),
        (EvidenceContext(liquidity_usd=0), "illiquid_context"),
        (EvidenceContext(spread=0.5), "wide_spread_context"),
    ],
)
def test_context_qualification(market, now, context, reason):
    e, r = engine(), relation(now)
    train(e, r, market, now)
    for i in (3, 4):
        snapshots, at = pair(market, now, i, 0.2)
        evidence = e.observe(r, snapshots, at, context)
        assert not evidence.qualified and reason in evidence.reasons


def test_logical_constraints_require_review(market, now):
    e, r = engine(), relation(now, "mutually_exclusive")
    snapshots, at = pair(market, now, 0, 0.3)
    evidence = e.observe(r, snapshots, at, EvidenceContext())
    assert "unverified_settlement_constraint" in evidence.reasons
    reviewed = relation(
        now,
        "mutually_exclusive",
        rule_verified=True,
        rule_description="Reviewed same-event exclusive settlement",
    )
    e = engine()
    for i in range(5):
        snapshots, at = pair(market, now, i, 0.3)
        evidence = e.observe(reviewed, snapshots, at, EvidenceContext(settlement_reviewed=True))
    assert evidence.qualified
    assert evidence.regime == "constraint_inconsistency"


def test_implication_is_directional(market, now):
    e, r = engine(), relation(now, "implication", rule_verified=True, rule_description="A implies B")
    for i in range(5):
        snapshots, at = pair(market, now, i, -0.2)
        evidence = e.observe(r, snapshots, at, EvidenceContext(settlement_reviewed=True))
    assert not evidence.qualified and "constraint_satisfied" in evidence.reasons


def test_conditional_not_misrepresented_as_constraint(market, now):
    e, r = (
        engine(),
        relation(now, "conditional", rule_verified=True, rule_description="Conditional dependence"),
    )
    snapshots, at = pair(market, now, 0, 0.3)
    evidence = e.observe(r, snapshots, at, EvidenceContext(settlement_reviewed=True))
    assert not evidence.qualified and "conditional_joint_probability_required" in evidence.reasons


def test_gap_resets_persistence(market, now):
    e, r = engine(), relation(now)
    train(e, r, market, now)
    for i in [3, 200]:
        snapshots, at = pair(market, now, i, 0.2)
        evidence = e.observe(r, snapshots, at, EvidenceContext())
        assert not evidence.qualified and evidence.persistence == 1


def test_replay_deterministic_and_future_does_not_train(market, now):
    r = relation(now)
    e1, e2 = engine(), engine()
    for i in range(5):
        snapshots, at = pair(market, now, i, 0.2 if i >= 3 else 0)
        if i == 2:
            future, _future_at = pair(market, now, 100, 0.3)
            assert not e1.observe(r, future, at, EvidenceContext()).qualified
        assert e1.observe(r, snapshots, at, EvidenceContext()) == e2.observe(
            r, snapshots, at, EvidenceContext()
        )


def test_graph_rejects_semantic_overwrite_and_invalid_identity(now):
    g = RelationshipGraph()
    r = relation(now)
    g.add(r)
    assert g.neighbors("m1") == (r,)
    with pytest.raises(ValueError, match="collision"):
        g.add(r.model_copy(update={"kind": "implication"}))
    with pytest.raises(ValueError, match="distinct"):
        g.add(r.model_copy(update={"id": "other", "market_ids": ("m1", "m1")}))


def test_discovery_uses_available_changes_and_labels_statistical(market, now):
    left, right = [], []
    values = [0.4, 0.43, 0.42, 0.46, 0.41, 0.49]
    for i, v in enumerate(values):
        snapshots, _at = pair(market, now, i, v - 0.4)
        left.append(snapshots["m1"])
        right.append(snapshots["m2"].model_copy(update={"probability": v * 0.9}))
    future = left[-1].available_at
    assert discover_statistical_relationship(left, right, now, minimum_samples=3) is None
    r = discover_statistical_relationship(left, right, future, minimum_samples=3)
    assert r and r.kind == "statistical" and not r.rule_verified
    assert "not a logical constraint" in r.rule_description
    with pytest.raises(ValueError, match="distinct"):
        discover_statistical_relationship(right, right, future, minimum_samples=3)


def test_capacity_and_policy_guard(now, market):
    with pytest.raises(ValueError):
        RelationshipPolicy(baseline_size=1)
    with pytest.raises(ValueError):
        EvidenceContext(spread=float("nan"))
    e = RelationshipEngine(RelationshipPolicy(max_relationships=1))
    snapshots, at = pair(market, now, 0)
    e.observe(relation(now), snapshots, at, EvidenceContext())
    with pytest.raises(ValueError, match="capacity"):
        e.observe(relation(now).model_copy(update={"id": "other"}), snapshots, at, EvidenceContext())


def test_missing_context_fails_closed(market, now):
    e = engine()
    snapshots, at = pair(market, now, 0)
    evidence = e.observe(relation(now), snapshots, at)
    assert not evidence.qualified and "missing_context" in evidence.reasons
