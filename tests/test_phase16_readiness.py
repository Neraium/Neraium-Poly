"""Controlled evidence fixtures; none is an authentic research observation."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from neraium_poly.research.phase16.calibration import calibration_cohort
from neraium_poly.research.phase16.readiness import build_readiness

START = datetime(2025, 1, 1, tzinfo=UTC)
BOUNDARY = START + timedelta(days=200)
CUTOFF = START + timedelta(days=500)


def row(i=0, split="train"):
    at = START + timedelta(days=i if split == "train" else 200 + i)
    rules = "CONTROLLED event pays one share for the specified binary outcome."
    h = sha256(rules.encode()).hexdigest()
    return {"forecast_id": f"controlled-{split}-{i}", "event_id": f"controlled-event-{split}-{i}",
        "market_id": f"controlled-market-{split}-{i}", "token_id": f"controlled-token-{split}-{i}",
        "dependency_group": f"controlled-parent-{split}-{i}", "independence_reviewed": True,
        "probability_semantics": "binary_terminal_event_probability", "uses_market_features": False,
        "domain": "controlled", "model_version": "fixture-v1", "feature_version": "fixture-v1",
        "contract_type": "controlled_terminal_binary", "forecast_sha256": "1" * 64,
        "model_sha256": "2" * 64, "dataset_sha256": "3" * 64, "outcome_proof_sha256": "4" * 64,
        "resolution_rules": rules, "resolution_rules_sha256": h, "outcome_rules_sha256": h,
        "forecast_at": at.isoformat(), "recorded_at": at.isoformat(),
        "evidence_available_at": at.isoformat(), "evidence_cutoff": at.isoformat(),
        "model_training_cutoff": (START - timedelta(days=1) if split == "train" else BOUNDARY - timedelta(days=1)).isoformat(),
        "market_at": at.isoformat(), "market_available_at": at.isoformat(),
        "outcome_at": (at + timedelta(hours=1)).isoformat(), "outcome_available_at": (at + timedelta(hours=2)).isoformat(),
        "probability": .8 if i % 2 else .2, "market_probability": .5, "outcome": i % 2, "split": split}


def report(rows, **kwargs):
    return calibration_cohort(rows, cutoff=CUTOFF, heldout_start=BOUNDARY, **kwargs)


def test_empty_or_unverified_cohort_does_not_invent_scores_or_authority():
    result = report([])
    assert result["metrics"] is None and result["training_events"] == result["heldout_events"] == 0
    result = report([row()])
    assert result["rejections"] == {"independent_raw_replay_required": 1}
    assert not result["certification_authority"] and not result["experimental_admission_authority"]


def test_verified_chronological_group_cohort_scores_with_baseline_and_uncertainty():
    rows = [row(i) for i in range(100)] + [row(i, "heldout") for i in range(100)]
    r = report(rows, verify_raw=lambda _r: True)
    assert r["cohort_sufficient"] and r["training_events"] == r["heldout_events"] == 100
    assert r["metrics"]["brier"] == pytest.approx(.04)
    assert r["metrics"]["market_brier"] == .25
    assert r["metrics"]["paired_brier_difference"] == pytest.approx(-.21)
    assert r["metrics"]["paired_brier_difference_95_bound"][1] > 0
    assert not r["metrics"]["forecasting_superiority_supported"]
    assert sum(b["count"] for b in r["metrics"]["reliability"]) == 100
    assert r["metrics"]["trading_advantage"] is None
    assert not r["certification_authority"]


def test_repeated_snapshots_select_earliest_and_hash_is_order_invariant():
    first = row(); later = deepcopy(first)
    later.update(forecast_id="later-fixture", forecast_at=(START + timedelta(minutes=1)).isoformat(),
                 recorded_at=(START + timedelta(minutes=1)).isoformat(), market_at=(START + timedelta(minutes=1)).isoformat(),
                 market_available_at=(START + timedelta(minutes=1)).isoformat())
    left = report([later, first], verify_raw=lambda _r: True)
    right = report([first, later], verify_raw=lambda _r: True)
    assert left == right
    assert left["accepted_forecast_ids"] == [first["forecast_id"]]
    assert left["rejections"]["repeated_dependency_group"] == 1


def test_cross_split_correlated_events_quarantined_not_double_counted():
    train, held = row(), row(0, "heldout")
    held["dependency_group"] = train["dependency_group"]
    result = report([train, held], verify_raw=lambda _r: True)
    assert result["training_events"] == result["heldout_events"] == 0
    assert "cross_split_dependency_groups" in result["blockers"]
    assert result["metrics"] is None


@pytest.mark.parametrize("field,value,reason", [
    ("outcome_rules_sha256", "0" * 64, "outcome_resolution_rules_mismatch"),
    ("resolution_rules", "changed", "original_resolution_rules_hash_mismatch"),
    ("uses_market_features", True, "independent_terminal_semantics_required"),
    ("probability_semantics", "future_bid_mark", "independent_terminal_semantics_required"),
    ("independence_reviewed", False, "independent_group_review_required"),
    ("evidence_available_at", (START + timedelta(seconds=1)).isoformat(), "future_or_nonprospective_evidence"),
    ("recorded_at", (START + timedelta(seconds=31)).isoformat(), "future_or_nonprospective_evidence"),
    ("market_at", (START - timedelta(seconds=61)).isoformat(), "contemporaneous_baseline_required"),
    ("probability", float("nan"), "binary_scoring_values_required"),
])
def test_evidence_and_semantics_fail_closed(field, value, reason):
    r = row(); r[field] = value
    result = report([r], verify_raw=lambda _r: True)
    assert result["rejections"] == {reason: 1}
    assert result["metrics"] is None


def test_label_availability_embargo_and_model_cutoff_prevent_future_training():
    a, b = row(), row(0, "heldout")
    a["outcome_available_at"] = BOUNDARY.isoformat()
    result = report([a, b], verify_raw=lambda _r: True)
    assert "training_labels_cross_heldout_boundary" in result["blockers"]
    assert "heldout_model_training_cutoff_precedes_training_labels" in result["blockers"]


def test_verifier_failure_is_explicit_missing_evidence_not_scoring():
    def absent(_row):
        raise OSError("controlled missing source")
    assert report([row()], verify_raw=absent)["rejections"] == {"independent_raw_replay_failed": 1}


def test_mixed_model_version_blocks_cohort_even_when_each_record_replays():
    rows = [row(i) for i in range(100)] + [row(i, "heldout") for i in range(100)]
    rows[-1]["feature_version"] = "new-feature-selected-on-heldout"
    result = report(rows, verify_raw=lambda _r: True)
    assert result["metrics"] is None and "mixed_model_or_contract_cohort" in result["blockers"]


def test_wrong_certainty_reports_infinite_log_loss_without_fabricating_finite_score():
    rows = [row(i) for i in range(100)] + [row(i, "heldout") for i in range(100)]
    rows[-1]["probability"] = 0  # outcome1
    r = report(rows, verify_raw=lambda _r: True)
    assert r["metrics"]["model_log_loss"] == {"value": None, "status": "positive_infinity", "infinite_events": 1}


def test_readiness_unknown_and_stale_data_never_means_ready_or_profitable():
    r = build_readiness({}, now=START)
    assert r["status"] == "insufficient_evidence" and r["estimated_executable_edge"] is None
    assert r["calibration"]["metrics"] is None and not r["model_promotion_authority"]
    history = {"last_observation_at": (START - timedelta(seconds=16)).isoformat(), "tokens_tracked": 1,
               "current_observations": 100, "valid_observations": 100, "current_matured_labels": 30,
               "span_seconds": 600, "max_gap_seconds": 5}
    r = build_readiness(history, execution={"estimated_net_edge": -.01}, now=START)
    assert "current_qualified_quote_stale" in r["insufficient_evidence"]
    assert "estimated_edge_below_unchanged_0_03_threshold" in r["market_conditions"]
    assert not r["mark_labels_are_independent_outcome_events"]


def test_readiness_distinguishes_defects_from_cost_rejection_and_keeps_gates():
    history = {"last_observation_at": (START + timedelta(seconds=1)).isoformat(), "current_observations": True}
    r = build_readiness(history, execution={"estimated_net_edge": float("inf")}, now=START)
    assert r["status"] == "implementation_defect" and r["estimated_executable_edge"] is None
    assert "future_history_timestamp" in r["implementation_defects"]
    assert r["minimum_net_edge"] == .03 and r["calibration"]["required_training_events"] == 100


def test_per_token_not_aggregate_history_and_exact_source_receipt_freshness():
    token = {"token_id": "controlled-token", "market_id": "controlled-market", "event_id": "controlled-parent",
             "observations": 40, "matured_labels": 20, "span_seconds": 300, "max_gap_seconds": 5,
             "latest_source_at": START.isoformat(), "latest_available_at": START.isoformat(),
             "execution_evidence_complete": True}
    history = {"last_observation_at": START.isoformat(), "current_observations": 40,
               "current_matured_labels": 20, "span_seconds": 300, "max_gap_seconds": 5,
               "per_token": [token]}
    r = build_readiness(history, now=START)
    assert r["eligible_mark_tokens"] == ["controlled-token"]
    assert r["status"] == "insufficient_evidence"  # no terminal calibration or cost evidence
    history["per_token"] = [{**token, "token_id": f"controlled-{i}", "observations": 5, "matured_labels": 3} for i in range(8)]
    r = build_readiness(history, now=START)
    assert not r["eligible_mark_tokens"]
    assert "per_token_causal_depth_history_and_matured_marks_required" in r["insufficient_evidence"]
    history["per_token"] = [{**token, "latest_source_at": (START-timedelta(seconds=16)).isoformat()}]
    r = build_readiness(history, now=START)
    assert not r["eligible_mark_tokens"] and r["freshness"]["source_age_seconds"] == 16
    assert "current_qualified_quote_stale" in r["insufficient_evidence"]
    history["per_token"] = [{**token, "latest_available_at": (START+timedelta(seconds=1)).isoformat()}]
    r = build_readiness(history, now=START)
    assert not r["eligible_mark_tokens"] and r["status"] == "implementation_defect"


def test_subthreshold_edge_is_not_mislabeled_as_missing_history_or_implementation_bug():
    token = {"token_id": "controlled-token", "market_id": "controlled-market", "event_id": "controlled-parent",
             "observations": 40, "matured_labels": 20, "span_seconds": 300, "max_gap_seconds": 5,
             "latest_source_at": START.isoformat(), "latest_available_at": START.isoformat(),
             "execution_evidence_complete": True}
    history = {"current_observations": 40, "current_matured_labels": 20, "span_seconds": 300,
               "max_gap_seconds": 5, "per_token": [token]}
    calibration = {"training_events": 100, "heldout_events": 100, "cohort_sufficient": True,
                   "metrics": {"fixture": True}, "calibration_status": "controlled_fixture"}
    r = build_readiness(history, execution={"estimated_net_edge": .02}, calibration=calibration, now=START)
    assert r["status"] == "cost_threshold_not_met"
    assert r["insufficient_evidence"] == r["implementation_defects"] == []
    assert not r["experimental_admission_authority"] and not r["certification_authority"]


def test_cohort_byte_budget_and_json_shape_fail_closed():
    r = row(); r["unbounded_notes"] = "x" * (256 * 1024)
    with pytest.raises(ValueError, match="byte_budget"):
        report([r], verify_raw=lambda _r: True)
    with pytest.raises(TypeError, match="canonical_json"):
        report([["not", "a", "record"]], verify_raw=lambda _r: True)


def test_matured_mark_readiness_is_distinct_from_terminal_probability_calibration():
    token = {"token_id": "controlled-token", "market_id": "controlled-market", "event_id": "controlled-parent",
             "observations": 40, "matured_labels": 20, "span_seconds": 300, "max_gap_seconds": 5,
             "latest_source_at": START.isoformat(), "latest_available_at": START.isoformat(),
             "execution_evidence_complete": True}
    history = {"current_observations": 40, "current_matured_labels": 20, "span_seconds": 300,
               "max_gap_seconds": 5, "per_token": [token]}
    result = build_readiness(history, execution={"estimated_net_edge_per_share": .04}, now=START)
    assert result["status"] == "insufficient_evidence"
    assert result["mark_research_readiness"]["status"] == "research_prerequisites_observed"
    assert not result["mark_research_readiness"]["outcome_probability_calibration_applicable"]
    assert not result["mark_research_readiness"]["formal_certification_and_order_authority"]
    history["per_token"][0]["observations"] = 40.5
    assert build_readiness(history, now=START)["eligible_mark_tokens"] == []
