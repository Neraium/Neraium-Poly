"""Controlled source records; never authentic market evidence or trade signals."""
import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase15.relationships import (
    METADATA_SOURCE,
    RelationshipResearch,
    qualify_cross_domain_driver,
)

START = datetime(2026, 11, 6, 20, tzinfo=UTC)


def frame(i=0, left=.3, right=.6):
    at = START + timedelta(seconds=20*i)
    common = {"schema_version": "1.0", "timestamp": at.isoformat(), "available_at": at.isoformat()}
    markets, books = [], []
    for n, midpoint in enumerate((left, right)):
        markets.append({**common, "id": f"fixture-meta-{n}", "source": METADATA_SOURCE,
            "market_id": f"fixture-market-{n}", "event_id": "fixture-parent", "token_id": f"fixture-token-{n}",
            "question": f"Controlled unrelated outcome {n}", "outcome": "YES", "probability": midpoint,
            "status": "active", "resolution_rules": "Controlled rules; not a logically reviewed exhaustive set"})
        books.append({**common, "id": f"fixture-book-{n}-{i}", "source": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            "market_id": f"fixture-market-{n}", "token_id": f"fixture-token-{n}", "complete": True,
            "bids": [{"price": midpoint-.002, "size": 30}], "asks": [{"price": midpoint+.002, "size": 20}]})
    return {"markets": markets, "books": books}, at


def test_shared_parent_is_only_statistical_graph_eligibility_not_logical_or_execution():
    f, now = frame(); engine = RelationshipResearch()
    result = engine.observe(f, observed_at=now)
    assert result["registered_statistical_candidates"] == 1
    assert result["results"][0]["status"] == "warming_up"
    assert result["cross_domain_reviewed_findings"] == result["reviewed_logical_constraints"] == 0
    assert not result["trading_authority"] and not result["certification_authority"]
    definition = next(iter(engine.definitions.values()))
    assert definition["metadata_sha256"] == [digest(m) for m in f["markets"]]
    assert definition["review_scope"] == "shared_parent_statistical_eligibility_only"
    assert "USD_per_outcome_share_not_independent_probability" in result["semantics"]
    book = f["books"][0]
    row = engine.engine.states[definition["id"]]["rows"][0]
    assert row[4] == digest([digest(book), definition["semantic_sha256"][0]])
    tampered = {**definition, "kind": "logical_probability_constraint"}
    assert engine._review_definition(tampered) is False


def test_yes_no_same_market_tokens_and_duplicate_contracts_do_not_form_edges():
    f, now = frame()
    f["markets"][1]["market_id"] = f["markets"][0]["market_id"]
    f["markets"][1]["outcome"] = "NO"
    assert RelationshipResearch().observe(f, observed_at=now)["registered_statistical_candidates"] == 0
    f["markets"][1]["outcome"] = "YES"
    result = RelationshipResearch().observe(f, observed_at=now)
    assert result["registered_statistical_candidates"] == 0
    assert result["source_rejections_cumulative"]["duplicate_market_or_token_identity"] == 1


@pytest.mark.parametrize("change,reason", [
    ({"timestamp": (START-timedelta(seconds=16)).isoformat(), "available_at": START.isoformat()}, "stale_or_future_source_quote"),
    ({"available_at": (START+timedelta(seconds=1)).isoformat()}, "stale_or_future_source_quote"),
    ({"market_id": "wrong-market"}, "source_quote_market_identity_mismatch"),
    ({"source": "https://untrusted.invalid"}, "source_quote_market_identity_mismatch"),
    ({"asks": []}, "incomplete_executable_quote"),
    ({"complete": False}, "incomplete_executable_quote"),
])
def test_stale_incomplete_mismatched_or_future_books_do_not_evaluate(change, reason):
    f, now = frame(); f["books"][0].update(change)
    result = RelationshipResearch().observe(f, observed_at=now)
    assert result["engine"]["evaluations"] == 0
    assert result["source_rejections_cumulative"][reason] == 1


def test_duplicate_books_quarantined_and_contract_changes_require_new_review():
    f, now = frame(); f["books"].append(deepcopy(f["books"][0]))
    assert RelationshipResearch().observe(f, observed_at=now)["engine"]["evaluations"] == 0
    f, now = frame(); engine = RelationshipResearch(); engine.observe(f, observed_at=now)
    f, now = frame(1); f["markets"][0]["resolution_rules"] = "Changed source rules"
    result = engine.observe(f, observed_at=now)
    assert result["engine"]["evaluations"] == 1
    assert result["source_rejections_cumulative"]["contract_semantics_changed_requires_new_review"] == 1


def test_half_spread_uncertainty_and_raw_hash_verifier_cannot_self_assert():
    f, now = frame(); engine = RelationshipResearch(); engine.observe(f, observed_at=now)
    market, book = engine.current["fixture-token-0"]
    row = {"entity_id": market.token_id, "semantics": "binary_event_probability"}
    assert engine._review_observation(row) is False
    assert book.asks[0].price-book.bids[0].price == pytest.approx(.004)
    # Broken raw replay denies even before the joint engine could claim evidence.
    identity = next(iter(engine.definitions)); engine.proofs[identity][0]["question"] = "tampered"
    assert not engine._review_definition(engine.definitions[identity])


def test_chronological_replay_restart_and_duplicate_quote_do_not_add_persistence():
    engine = RelationshipResearch()
    for i in range(10):
        f, now = frame(i, left=.2+i*.01, right=.3+i*.02)
        result = engine.observe(f, observed_at=now)
        assert result["results"][0]["status"] == "warming_up"
    restored = RelationshipResearch(); restored.restore(engine.checkpoint())
    f, now = frame(10, left=.4, right=.3)
    assert restored.observe(f, observed_at=now) == engine.observe(f, observed_at=now)
    # Same exact source books at a later receipt/cycle cannot add persistence.
    result = restored.observe(f, observed_at=now+timedelta(seconds=1))
    assert result["results"][0]["reason"] == "duplicate_pair_does_not_add_persistence"
    assert restored.observe(f, observed_at=now)["reason"] == "non_increasing_research_cycle"


def test_constant_quotes_have_no_baseline_and_no_fabricated_findings():
    engine = RelationshipResearch()
    for i in range(15):
        f, now = frame(i); result = engine.observe(f, observed_at=now)
    assert result["engine"]["persistent_findings"] == 0
    assert result["results"][0]["reason"] == "insufficient_joint_variation_for_relationship_baseline"
    assert engine.engine.config["warmup"] == 10
    assert engine.engine.config["persistence"] == 3
    assert engine.engine.config["persistence_seconds"] == 60


def test_checkpoint_corruption_and_capacity_bounds():
    f, now = frame(); engine = RelationshipResearch(); engine.observe(f, observed_at=now)
    checkpoint = engine.checkpoint(); checkpoint["proofs"][next(iter(checkpoint["proofs"]))][0]["question"] = "corrupt"
    with pytest.raises(ValueError, match="integrity"):
        RelationshipResearch().restore(checkpoint)
    with pytest.raises(ValueError, match="budget"):
        RelationshipResearch(max_pairs=21)
    with pytest.raises(ValueError, match="bounded_market_frame"):
        engine.observe({"markets": [{}]*1001, "books": []}, observed_at=now+timedelta(seconds=1))


def driver():
    raw = "Controlled driver evidence"
    return {"kind": "statistical_relationship", "left_domain": "weather", "right_domain": "finance",
        "hypothesis": "Controlled predeclared driver hypothesis", "available_at": START.isoformat(),
        "source_timestamp": START.isoformat(), "retrieved_at": START.isoformat(),
        "source": "https://official.example.invalid/fixture", "raw_evidence_utf8": raw,
        "raw_evidence_sha256": hashlib.sha256(raw.encode()).hexdigest()}


def test_cross_domain_driver_default_denies_no_logical_review_or_trading_authority():
    assert qualify_cross_domain_driver(driver(), observed_at=START)["reason"] == "independent_source_bound_driver_review_required"
    called = []
    def review(definition, source_bound_hash):
        called.append(source_bound_hash)
        return source_bound_hash == digest(definition)
    result = qualify_cross_domain_driver(driver(), observed_at=START, review=review)
    assert called == [digest(driver())] and result["status"] == "research_candidate_only"
    assert not result["logical_constraint_reviewed"] and not result["trading_authority"]
    assert qualify_cross_domain_driver({**driver(), "kind": "logical_probability_constraint"}, observed_at=START, review=review)["status"] == "withheld"
    assert qualify_cross_domain_driver({**driver(), "raw_evidence_utf8": "corrupt"}, observed_at=START, review=review)["status"] == "withheld"


def test_unavailable_cross_domain_reviewer_fails_closed():
    def unavailable(*_):
        raise RuntimeError("controlled_reviewer_unavailable")
    result = qualify_cross_domain_driver(driver(), observed_at=START, review=unavailable)
    assert result["status"] == "withheld" and not result["trading_authority"]
    assert result["reason"] == "controlled_reviewer_unavailable"


def test_persistent_joint_change_requires_time_and_remains_descriptive_only():
    engine = RelationshipResearch()
    findings = []
    for i in range(22):
        x = .2 + .005*i
        y = x if i < 10 else .7-.005*(i-10)
        f, now = frame(i, left=x, right=y)
        result = engine.observe(f, observed_at=now)["results"][0]
        if i in (10, 11, 12):
            assert not result.get("persistent", False)  # 40 seconds is insufficient.
        if result.get("finding_new"):
            findings.append(result)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["persistence_count"] >= 3
    assert (datetime.fromisoformat(finding["evaluated_at"])-datetime.fromisoformat(finding["persistence_since"])).total_seconds() >= 60
    assert not finding["executable_opportunity"] and not finding["causality_verified"]
    assert finding["statistical_significance"] is None
