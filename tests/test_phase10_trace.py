"""Controlled fixtures only; never represented as authentic opportunity evidence."""

from datetime import timedelta

import pytest
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine
from neraium_poly.experimental.trace import DecisionTrace, category_for
from test_experimental_strategies import frame, warm


def test_pre_dedup_funnel_reports_unchanged_valid_observations():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80)
    signals = engine.evaluate_frame(f, now)
    trace = DecisionTrace()
    trace.record_engine(f, signals, engine.status(), now, engine.last_trace)
    assert engine.last_trace["short_horizon"]["candidate_signals"] == 1
    assert not signals[0].eligible
    assert engine.evaluate_frame(f, now) == []
    trace.record_engine(f, [], engine.status(), now, engine.last_trace)
    epoch = trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
    cycle = trace.status()["latest_cycle"]["strategies"]["short_horizon"]
    assert epoch["markets_considered"] == epoch["valid_observations"] == 2
    assert epoch["rejected_signals"] == 2
    assert epoch["emitted_signals"] == cycle["duplicate_signals"] == 1
    assert cycle["emitted_signals"] == 0
    assert epoch["reasons"]["conservative_roundtrip_edge_insufficient"]["count"] == 2


def test_cost_decomposition_exactly_matches_existing_admission_edge():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80, bid=0.45)
    (signal,) = engine.evaluate_frame(f, now)
    d = signal.diagnostics
    assert d["forecast_gross_edge"] - d["uncertainty_haircut"] - d["entry_fee_bound"] - d[
        "exit_fee_bound"
    ] - d["roundtrip_slippage_bound"] == pytest.approx(signal.estimated_net_edge)
    assert d["minimum_net_edge"] == 0.03
    assert signal.eligible and d["candidate_before_costs"] == 1


def test_missing_data_and_structural_evidence_are_not_candidates():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon", "persistent_relationship"])
    warm(engine)
    f, now = frame(80, bid=0.45)
    signals = engine.evaluate_frame(f, now)
    assert engine.last_trace["short_horizon"]["candidate_signals"] == 1
    assert engine.last_trace["persistent_relationship"]["candidate_signals"] == 0
    f, now = frame(81, bid=0.45)
    engine.evaluate_frame(f, now + timedelta(seconds=16))
    assert engine.last_trace["short_horizon"]["valid_observations"] == 0
    assert engine.last_trace["short_horizon"]["candidate_signals"] == 0
    assert len(signals) == 2


def test_admission_execution_restart_idempotency_and_bounded_samples():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80, bid=0.45)
    (signal,) = engine.evaluate_frame(f, now)
    trace = DecisionTrace()
    trace.record_engine(f, [signal], engine.status(), now)
    rejected = {
        "status": "rejected",
        "intent": {"id": "controlled-intent"},
        "risk_decision": {"approved": False},
        "reasons": ["aggregate_exposure_limit"],
    }
    trace.record_admission(signal, rejected, now)
    trace.record_admission(signal, rejected, now)
    trace.record_execution("short_horizon", "controlled-partial", "partial", 2.0, now)
    restored = DecisionTrace()
    restored.restore(trace.checkpoint())
    restored.record_execution("short_horizon", "controlled-partial", "partial", 2.0, now)
    restored.record_execution("short_horizon", "controlled-expired", "expired", 0, now)
    row = restored.status()["phase10_epoch"]["strategies"]["short_horizon"]
    assert row["order_attempts"] == row["risk_rejections"] == row["fills"] == row["expired_orders"] == 1
    assert row["submitted_orders"] == 0
    assert row["reasons"]["aggregate_exposure_limit"]["category"] == "RISK REJECTION"
    for n in range(20):
        changed = signal.model_copy(update={"id": f"controlled-signal-{n}"})
        restored.record_admission(changed, rejected, now)
    assert (
        len(
            restored.status()["phase10_epoch"]["strategies"]["short_horizon"]["reasons"][
                "aggregate_exposure_limit"
            ]["samples"]
        )
        == 3
    )


def test_categories_and_checkpoint_fail_closed():
    assert category_for("multi_leg_execution_and_hedging_not_supported") == "STRATEGY LIMITATION"
    assert (
        category_for("independent_context_verified_labels_and_calibration_required")
        == "CERTIFICATION DEPENDENCY"
    )
    assert category_for("stale_book") == "MISSING EVIDENCE"
    trace = DecisionTrace()
    with pytest.raises(ValueError):
        trace.restore({"schema_version": "bad"})
    with pytest.raises(ValueError):
        trace.record_execution("short_horizon", "x", "partial", float("nan"), frame(0)[1])
