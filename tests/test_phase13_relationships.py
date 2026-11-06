"""Controlled temporal relationship fixtures, not operational market findings."""

from datetime import timedelta

import pytest
from neraium_poly.research.phase13.contracts import SportsMapping
from neraium_poly.research.phase13.models import predict_game
from neraium_poly.research.phase13.relationships import SportsRelationshipResearch
from test_phase13_models import NOW, corpus


def observations(league="NBA"):
    games, target = corpus(league)
    p = predict_game(games, target, "A", NOW, method="frequency" if league == "NFL" else "elo")
    m = SportsMapping(
        event_id="e", market_id="m", token_id="t", game_id=target.game_id, league=league,
        provider=target.provider, selected_team_id="A", opponent_team_id="B", event_start=target.starts_at,
        rules_sha256="c" * 64, mapping_sha256="d" * 64, artifact_sha256=target.artifact_sha256,
    )
    return p, m


def observe(engine, prediction, mapping, i, market=0.5, **kwargs):
    now = NOW + timedelta(seconds=30 * i)
    arguments = {"market_probability": market, "market_timestamp": now,
                 "market_available_at": now, "evidence_sha256": f"{i:064x}", "now": now}
    arguments.update(kwargs)
    return engine.observe(mapping, prediction, **arguments)


def test_requires_temporal_baseline_and_persistence_not_single_deviation():
    p, m = observations()
    engine = SportsRelationshipResearch()
    for i in range(10):
        assert observe(engine, p, m, i)["status"] == "warming_up"
    one = observe(engine, p, m, 10, market=0.3)
    assert one["status"] == "observing"
    assert one["persistence_count"] == 1
    assert observe(engine, p, m, 11, market=0.3)["status"] == "observing"
    finding = observe(engine, p, m, 12, market=0.3)
    assert finding["status"] == "persistent_descriptive_relationship_change"
    assert finding["executable_opportunity"] is False
    assert finding["causal_hypothesis_verified"] is False
    assert finding["logical_constraint_verified"] is False
    assert finding["model_sha256"] == p.model_sha256


def test_noise_and_duplicate_evidence_do_not_prove_relationship_change():
    p, m = observations()
    engine = SportsRelationshipResearch()
    for i in range(10):
        observe(engine, p, m, i)
    observe(engine, p, m, 10, market=0.3)
    duplicate = observe(engine, p, m, 11, market=0.3, evidence_sha256=f"{10:064x}")
    assert duplicate["reason"] == "duplicate_evidence_does_not_add_persistence"
    normal = observe(engine, p, m, 12, market=0.51)
    assert normal["persistence_count"] == 0
    assert engine.findings == 0


def test_recovery_preserves_persistence_and_no_future_information():
    p, m = observations()
    first = SportsRelationshipResearch()
    for i in range(11):
        observe(first, p, m, i, market=0.3 if i == 10 else 0.5)
    restored = SportsRelationshipResearch()
    restored.restore(first.checkpoint())
    for i in (11, 12):
        assert observe(first, p, m, i, market=0.3) == observe(restored, p, m, i, market=0.3)
    assert restored.findings == first.findings == 1
    assert observe(restored, p, m, 13, market_timestamp=NOW - timedelta(hours=1))["status"] == "withheld"
    future = p.model_copy(update={"cutoff": NOW + timedelta(hours=1)})
    assert observe(restored, future, m, 14)["reason"] == "fresh_causal_pre_event_model_market_pair_required"


def test_fractional_contract_compares_expected_payout_never_win_probability():
    p, m = observations("NFL")
    engine = SportsRelationshipResearch()
    for i in range(10):
        observe(engine, p, m, i)
    result = observe(engine, p, m, 10)
    assert result["model_market_residual"] == pytest.approx(p.uncertainty["expected_payout"] - 0.5)
    assert "not win_probability" in result["comparison"]


def test_checkpoint_rejects_unbounded_or_invalid_state():
    engine = SportsRelationshipResearch()
    p, m = observations()
    observe(engine, p, m, 0)
    checkpoint = engine.checkpoint()
    checkpoint["states"][next(iter(checkpoint["states"]))]["baseline"] = float("nan")
    with pytest.raises(ValueError, match="checkpoint state"):
        SportsRelationshipResearch().restore(checkpoint)
    with pytest.raises(ValueError, match="configuration"):
        SportsRelationshipResearch(warmup=1)
