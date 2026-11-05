"""Risk must bind the full causal research chain and preserve realized peaks."""

from datetime import timedelta

import pytest
from neraium_poly.contracts import (
    ModelProvenance,
    OrderIntent,
    ProbabilityEstimate,
    RelationshipEvidence,
    TradingOpportunity,
)
from neraium_poly.risk import RiskEngine, RiskLimits


def allocation(now, market, book, suffix="1"):
    def at(seconds):
        value = now + timedelta(seconds=seconds)
        return {"timestamp": value, "available_at": value, "source": "provenance-fixture"}

    model = ModelProvenance(
        **at(-30),
        id="model",
        model_name="reviewed-fixture",
        model_version="1",
        training_end=now - timedelta(days=1),
        artifact_hash="fixture-sha256",
        approved=True,
        calibration_samples=100,
    )
    evidence = RelationshipEvidence(
        **at(-3),
        id="evidence-" + suffix,
        relationship_id="relationship",
        sample_count=100,
        persistence=4,
        strength=3,
        confidence=0.9,
        qualified=True,
        observation_ids=("observation-" + suffix,),
    )
    estimate = ProbabilityEstimate(
        **at(-2),
        id="estimate-" + suffix,
        market_id=market.market_id,
        token_id=market.token_id,
        probability=0.65,
        lower=0.55,
        upper=0.75,
        model_id=model.id,
        calibrated=True,
        evidence_ids=(evidence.id,),
    )
    opportunity = TradingOpportunity(
        **at(-1),
        id="opportunity-" + suffix,
        market_id=market.market_id,
        token_id=market.token_id,
        event_id=market.event_id,
        estimate_id=estimate.id,
        evidence_ids=(evidence.id,),
        market_probability=0.4,
        estimated_probability=0.65,
        conservative_probability=0.55,
        net_edge=0.14,
        fee_rate=0.02,
        slippage=0.002,
        liquidity=100,
        calibrated=True,
    )
    intent = OrderIntent(
        **at(0),
        id="intent-" + suffix,
        client_order_id="client-" + suffix,
        market_id=market.market_id,
        token_id=market.token_id,
        event_id=market.event_id,
        opportunity_id=opportunity.id,
        limit_price=0.4,
        quantity=10,
        expires_at=now + timedelta(minutes=1),
    )
    return [intent, opportunity, market, book, [evidence]], {"estimate": estimate, "model": model}


def test_causal_qualified_chain_is_approved(now, market, book):
    args, provenance = allocation(now, market, book)
    engine = RiskEngine()
    assert engine.approve(*args, now=now, **provenance).approved
    engine.close()


@pytest.mark.parametrize("ids", [(), ("unrelated",), ("evidence-1", "evidence-1")])
def test_estimate_must_cite_exact_qualified_evidence(now, market, book, ids):
    args, provenance = allocation(now, market, book)
    provenance["estimate"] = provenance["estimate"].model_copy(update={"evidence_ids": ids})
    engine = RiskEngine()
    result = engine.approve(*args, now=now, **provenance)
    assert not result.approved and "estimate_evidence_mismatch" in result.reasons
    assert engine.snapshot(now=now)["reserved"] == 0
    engine.close()


@pytest.mark.parametrize("stage", ["evidence", "estimate", "opportunity", "model"])
def test_every_provenance_link_precedes_its_consumer(now, market, book, stage):
    args, provenance = allocation(now, market, book)
    if stage == "evidence":
        args[4] = [args[4][0].model_copy(update={"timestamp": now, "available_at": now})]
    elif stage == "estimate":
        provenance["estimate"] = provenance["estimate"].model_copy(
            update={"timestamp": now, "available_at": now}
        )
    elif stage == "opportunity":
        args[0] = args[0].model_copy(
            update={"timestamp": now - timedelta(seconds=2), "available_at": now - timedelta(seconds=2)}
        )
    else:
        provenance["model"] = provenance["model"].model_copy(update={"timestamp": now, "available_at": now})
    engine = RiskEngine()
    result = engine.approve(*args, now=now, **provenance)
    assert not result.approved and "noncausal_provenance" in result.reasons
    engine.close()


def test_settled_win_sets_peak_and_later_loss_trips_drawdown(now, market, book):
    # Losses below the original $500 bankroll can still breach the true peak.
    limits = RiskLimits(drawdown_fraction=0.0078, daily_loss_fraction=1)
    engine = RiskEngine(limits=limits)
    args, provenance = allocation(now, market, book)
    decision = engine.approve(*args, now=now, **provenance)
    assert decision.approved
    engine.record_fill(args[0], decision, 10, 0.4, 0.08, now=now)
    assert engine.settle(
        market.token_id, 1, now=now, rules_verified=True, resolution_source="fixture"
    ) == pytest.approx(5.92)
    state = engine.snapshot(now=now)
    assert state["peak"] == pytest.approx(505.92)
    assert state["peak"] == pytest.approx(state["equity"])
    args, provenance = allocation(now, market, book, suffix="2")
    decision = engine.approve(*args, now=now, **provenance)
    assert decision.approved
    engine.record_fill(args[0], decision, 10, 0.4, 0.08, now=now)
    engine.settle(market.token_id, 0, now=now, rules_verified=True, resolution_source="fixture")
    state = engine.snapshot(now=now)
    assert state["equity"] == pytest.approx(501.84)
    assert state["drawdown"] == pytest.approx(4.08)
    assert state["peak"] == pytest.approx(505.92)
    args, provenance = allocation(now, market, book, suffix="3")
    rejected = engine.approve(*args, now=now, **provenance)
    assert not rejected.approved and "drawdown_circuit_breaker" in rejected.reasons
    # Repeated settlement cannot create cash or alter the peak.
    assert engine.settle(market.token_id, 1, now=now, rules_verified=True, resolution_source="fixture") == 0
    assert engine.snapshot(now=now)["peak"] == pytest.approx(505.92)
    engine.close()
