"""Controlled event fixtures only; never reported as genuine forecast evidence."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase12.contracts import CanonicalEvent, EventEvidence, VerifiedEventOutcome
from neraium_poly.research.phase12.models import (
    build_samples,
    chronological_split,
    probability_metrics,
    run_event_models,
)
from neraium_poly.research.phase12.relationships import (
    EventRelationshipEngine,
    evaluate_logical_constraint,
    run_event_relationships,
)
from test_experimental_account import book, fee, market

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RULE = "CONTROLLED fixture final binary event rule"
RULE_HASH = hashlib.sha256(RULE.encode()).hexdigest()


def evidence(n, kind, at, payload, *, available=None, independent=False):
    return EventEvidence(
        id=f"controlled-{kind}-{n}",
        timestamp=at,
        available_at=available or at,
        source="https://controlled.invalid/fixture",
        event_id=f"e{n}",
        market_id=f"m{n}",
        kind=kind,
        payload=payload,
        independent_of_market_price=independent,
        content_sha256=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def dataset(count=60):
    events = []
    ev = []
    outcomes = []
    for n in range(count):
        at = NOW + timedelta(days=n)
        events.append(
            CanonicalEvent(
                id=f"event-{n}",
                timestamp=at - timedelta(days=2),
                available_at=at - timedelta(days=2),
                source="https://controlled.invalid",
                event_id=f"e{n}",
                market_id=f"m{n}",
                question="CONTROLLED fixture?",
                token_ids=(f"t{n}",),
                outcomes=("YES",),
                resolution_rules=RULE,
                resolution_source="https://controlled.invalid/oracle",
                closes_at=at + timedelta(hours=1),
                dependency_group=f"g{n}",
                independence_reviewed=True,
                provenance={"historical_rules_verified": True},
                category="CONTROLLED",
            )
        )
        ev.append(evidence(n, "market_price", at, {"probability": 0.5, "token_id": f"t{n}"}))
        ev.append(
            evidence(
                n,
                "external_context",
                at - timedelta(hours=1),
                {"features": {"controlled_signal": n % 2}, "feature_provenance_reviewed": True},
                independent=True,
            )
        )
        outcomes.append(
            VerifiedEventOutcome(
                id=f"outcome-{n}",
                timestamp=at + timedelta(hours=1),
                available_at=at + timedelta(hours=2),
                source="https://controlled.invalid/proof",
                event_id=f"e{n}",
                market_id=f"m{n}",
                token_id=f"t{n}",
                payout=n % 2,
                resolution_rules_sha256=RULE_HASH,
                settled_at=at + timedelta(hours=1),
                verification_source="CONTROLLED fixture",
                proof_sha256=hashlib.sha256(
                    json.dumps({"finalized": True}, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                verification={"finalized": True},
            )
        )
    return {"manifest": {"dataset_sha256": "a" * 64}, "events": events, "evidence": ev, "outcomes": outcomes}


def test_terminal_models_real_split_metrics_and_no_promotion():
    report = run_event_models(dataset())
    assert report["split_counts"] == {"train": 36, "validation": 12, "heldout": 12, "purged": 0}
    assert report["status"] == "exploratory_evaluated"
    assert report["results"]["heldout"]["independent_logistic"]["brier"] < 0.25
    assert report["results"]["heldout"]["market_implied"]["brier"] == 0.25
    assert report["independent_forecasting_skill_established"] is False
    assert report["certification_authority"] is report["automatic_promotion"] is False
    assert report["certification_minimum"] == {"training": 100, "heldout": 100}


def test_future_price_context_and_settlement_are_not_backfilled():
    data = dataset(1)
    price = data["evidence"][0]
    data["evidence"][0] = price.model_copy(update={"available_at": price.timestamp + timedelta(days=3)})
    report = run_event_models(data)
    assert report["funnel"]["rejections"]["market_observation_not_available_at_decision"] == 1
    assert report["results"] is None and report["terminal_probability"]["brier"] is None
    data = dataset(1)
    data["outcomes"][0] = data["outcomes"][0].model_copy(update={"settled_at": NOW})
    assert build_samples(data)[3]["rejections"]["outcome_already_resolved_at_decision"] == 1
    data = dataset(1)
    context = data["evidence"][1]
    data["evidence"][1] = context.model_copy(update={"available_at": NOW + timedelta(seconds=1)})
    assert build_samples(data)[3]["rejections"]["independent_predecision_numeric_context_missing"] == 1


def test_unreviewed_independence_and_market_only_never_become_independent_model():
    data = dataset(1)
    data["events"][0] = data["events"][0].model_copy(update={"independence_reviewed": False})
    assert build_samples(data)[1] == []
    data = dataset(1)
    data["evidence"] = [data["evidence"][0]]
    report = run_event_models(data)
    assert report["market_comparison_sample_count"] == 1
    assert report["split_counts"]["train"] == 0 and report["results"] is None


def test_rule_version_and_evidence_integrity_fail_closed():
    data = dataset(1)
    data["events"][0] = data["events"][0].model_copy(update={"provenance": {}})
    assert build_samples(data)[3]["rejections"]["point_in_time_rule_version_unverified"] == 1
    data = dataset(1)
    data["outcomes"][0] = data["outcomes"][0].model_copy(update={"resolution_rules_sha256": "b" * 64})
    assert build_samples(data)[3]["rejections"]["resolution_rules_outcome_mismatch"] == 1
    data = dataset(1)
    data["evidence"][0] = data["evidence"][0].model_copy(update={"payload": {"probability": 0.8}})
    with pytest.raises(ValueError, match="integrity"):
        build_samples(data)


def test_group_dedup_and_matured_label_purge():
    data = dataset(10)
    data["events"][1] = data["events"][1].model_copy(update={"dependency_group": "g0"})
    rows = build_samples(data)[1]
    assert len(rows) == 9 and len({r["dependency_group"] for r in rows}) == 9
    rows = build_samples(dataset())[1]
    rows[35]["label_available_at"] = NOW + timedelta(days=40)
    train, val, test, purged = chronological_split(rows)
    assert len(train) == 35 and purged == 1
    assert not ({r["dependency_group"] for r in train} & {r["dependency_group"] for r in val + test})


def test_heldout_outcomes_cannot_change_fit_or_validation_selection():
    data = dataset()
    first = run_event_models(data)
    for n in range(48, 60):
        data["outcomes"][n] = data["outcomes"][n].model_copy(
            update={"payout": 1 - data["outcomes"][n].payout}
        )
    second = run_event_models(data)
    assert first["training_parameters"] == second["training_parameters"]
    assert first["validation_selected_model"] == second["validation_selected_model"]
    assert first["results"]["heldout"] != second["results"]["heldout"]


def test_metrics_known_values_and_unknown_discrimination():
    x = probability_metrics([0.25, 0.75], [0, 1])
    assert x["brier"] == 0.0625 and x["auc"] == 1
    assert probability_metrics([0.5], [1])["auc"] is None
    assert probability_metrics([], [])["brier"] is None
    with pytest.raises(ValueError):
        probability_metrics([float("nan")], [1])


def frame(now):
    a = market(now, "a").model_copy(update={"event_id": "shared", "outcome": "YES", "resolution_rules": RULE})
    b = market(now, "b").model_copy(update={"event_id": "shared", "outcome": "YES", "resolution_rules": RULE})
    return SharedMarketFrame(
        timestamp=now,
        available_at=now,
        source="controlled-test",
        producer_health={"status": "ok"},
        markets=(a, b),
        books=(book(now, "a", ask=0.4), book(now, "b", ask=0.4)),
        fees={"a": fee(now), "b": fee(now)},
    )


def test_live_relationships_persist_statistical_baseline_without_logical_promotion():
    engine = EventRelationshipEngine()
    for n in range(22):
        report = engine.observe(frame(NOW + timedelta(seconds=n)), NOW + timedelta(seconds=n))
    assert report["relationships"] == 1 and report["evaluations"] == 1
    assert report["logical_constraints_verified"] == report["executable_opportunities"] == 0
    assert report["cumulative_relationship_evaluations"] == 22
    restored = EventRelationshipEngine()
    restored.restore(engine.checkpoint())
    assert restored.checkpoint() == engine.checkpoint()
    bad = frame(NOW).model_copy(update={"producer_health": {"status": "degraded"}})
    assert restored.observe(bad, NOW)["status"] == "withheld"
    assert restored.cycles == 22


def review(now):
    return {
        "kind": "exhaustive",
        "token_ids": ["a", "b"],
        "reviewed_at": now.isoformat(),
        "review_actor": "CONTROLLED reviewer",
        "payoff_scope_verified": True,
        "settlement_compatible": True,
        "review_evidence_ids": ["controlled-review"],
        "rule_hashes": {"a": RULE_HASH, "b": RULE_HASH},
    }


def test_logical_arithmetic_never_becomes_unsupported_executable_profit():
    result = evaluate_logical_constraint(review(NOW), frame(NOW), NOW)
    assert result["positive_reviewed_quote_discrepancy"]
    assert result["quote_level_net_difference"] > 0
    assert result["executable_opportunity"] is False
    result = evaluate_logical_constraint({"kind": "exhaustive", "token_ids": ["a", "b"]}, frame(NOW), NOW)
    assert result["quote_level_net_difference"] is None
    assert "independent_payoff_and_settlement_review_required" in result["reasons"]


def test_logical_constraints_reject_stale_missing_fees_depth_and_rule_mismatch():
    f = frame(NOW)
    stale = evaluate_logical_constraint(review(NOW), f, NOW + timedelta(seconds=16))
    assert "fresh_complete_executable_book_required" in stale["reasons"]
    nofees = evaluate_logical_constraint(review(NOW), f.model_copy(update={"fees": {}}), NOW)
    assert "verified_current_fee_required" in nofees["reasons"]
    thin = f.model_copy(update={"books": (book(NOW, "a", ask=0.4, size=1), book(NOW, "b", ask=0.4, size=1))})
    assert (
        "insufficient_atomic_bundle_depth_or_minimum_lot"
        in evaluate_logical_constraint(review(NOW), thin, NOW)["reasons"]
    )
    bad = review(NOW)
    bad["rule_hashes"]["a"] = "b" * 64
    assert "reviewed_rule_hash_mismatch" in evaluate_logical_constraint(bad, f, NOW)["reasons"]


def test_historical_relationships_distinguish_layers_and_preserve_nulls():
    r = run_event_relationships(dataset(1))
    assert r["logical_constraints_verified"] == r["executable_opportunities"] == 0
    assert r["independent_false_positive_rate"] is None
    assert len(r["classification_layers"]) == 4


def test_temperature_uses_validation_only_and_scores_are_terminal():
    r = run_event_models(dataset())
    assert r["training_parameters"]["validation_temperature"] in (0.5, 1, 2)
    assert "calibrated_independent_logistic" in r["results"]["heldout"]
    assert r["spec"]["target_definitions"]["terminal"].startswith("Verified binary final token payout")


def test_reserved_outcome_feature_and_corrupt_outcome_proof_reject():
    data = dataset(1)
    data["evidence"][1] = evidence(
        0,
        "external_context",
        NOW - timedelta(hours=1),
        {"features": {"outcome": 1}, "feature_provenance_reviewed": True},
        independent=True,
    )
    assert build_samples(data)[1] == []
    data = dataset(1)
    data["outcomes"][0] = data["outcomes"][0].model_copy(update={"proof_sha256": "b" * 64})
    with pytest.raises(ValueError, match="verification integrity"):
        build_samples(data)


def test_live_relationship_rejects_ambiguous_books_and_old_frame():
    engine = EventRelationshipEngine()
    f = frame(NOW)
    ambiguous = f.model_copy(update={"books": f.books + (f.books[0],)})
    with pytest.raises(ValueError, match="unambiguous event books"):
        engine.observe(ambiguous, NOW)
    assert engine.observe(f, NOW + timedelta(seconds=16))["status"] == "withheld"
    assert engine.cycles == 0
