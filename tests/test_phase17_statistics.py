"""Controlled statistical fixtures; never authentic market evidence."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase17.models import CANDIDATES, causal_forecasts
from neraium_poly.research.phase17.statistics import _holm, evaluate_experiments

START = datetime(2026, 11, 1, tzinfo=UTC)


def at(seconds):
    return (START+timedelta(seconds=seconds)).isoformat()


def point(i, *, token="token", event="parent", bid=None):
    bid = .4+i*.001 if bid is None else bid
    return {"id": f"point-{token}-{i}", "book_id": f"book-{token}-{i}",
            "token_id": token, "market_id": f"market-{token}", "event_id": event,
            "source_at": at(i*5), "available_at": at(i*5+.1), "observed_at": at(i*5+1),
            "bid_vwap": bid, "ask_vwap": bid+.01, "imbalance": .5,
            "rules_sha256": "a"*64, "execution_evidence_complete": True}


def row(i, decision, *, event=None, actual=.5, forecast=.5, reviewed=False):
    return {"id": f"row-{i}", "event_id": event or f"parent-{i}", "token_id": f"token-{i}",
            "decision_at": at(decision), "target_at": at(decision+60),
            "label_at": at(decision+60), "label_available_at": at(decision+61),
            "label_observed_at": at(decision+62), "actual_bid": actual, "baseline": .4,
            "forecasts": {"unchanged": .4, "reversion20": forecast,
                          "momentum20": forecast, "depthimbalance": forecast},
            "independence_reviewed": reviewed, "independence_evidence_sha256": "c"*64,
            "costs": {"executable": True, "gross_per_share": .05, "net_per_share": .03},
            "estimated_edge_by_candidate": {name: .04 for name in CANDIDATES}}


def evaluate(rows, verify=lambda _r: True):
    return evaluate_experiments(rows, training_end=at(300), validation_end=at(700),
                                cutoff=at(3000), verify_row=verify)


def test_fixed_formulas_use_exactly_twenty_prior_points_and_no_labels():
    points = [point(i) for i in range(21)]
    forecasts = causal_forecasts(points, cutoff=at(200))
    assert len(forecasts) == 1
    f = forecasts[0]
    assert f["point_id"] == "point-token-20"
    assert f["forecasts"] == pytest.approx({"unchanged": .42, "reversion20": .4095,
                                          "momentum20": .4305, "depthimbalance": .425})
    assert len(f["feature_point_ids"]) == 20 and f["point_id"] not in f["feature_point_ids"]
    assert f["feature_point_ids"][-1] == "point-token-19"
    assert not f["trading_authority"] and not f["certification_authority"]
    assert f["uncertainty"]["interval"] is None


def test_adding_or_modifying_future_points_cannot_change_an_earlier_forecast():
    points = [point(i) for i in range(30)]
    early = causal_forecasts(points, cutoff=at(105))
    later = deepcopy(points)
    for p in later[21:]:
        p.update(bid_vwap=.9, ask_vwap=.91, imbalance=-1)
    assert causal_forecasts(later, cutoff=at(105)) == early
    assert causal_forecasts(later, cutoff=at(300))[0] == early[0]


def test_history_is_separate_per_token_and_rules_epoch_and_gaps_reset():
    points = [point(i) for i in range(21)]
    points[-1]["rules_sha256"] = "b"*64
    assert causal_forecasts(points, cutoff=at(200)) == []
    points[-1] = point(80)
    assert causal_forecasts(points, cutoff=at(500)) == []
    assert causal_forecasts([point(i, token=str(i)) for i in range(30)], cutoff=at(200)) == []


def test_duplicate_conflict_quarantines_original_and_stale_future_input_rejected():
    points = [point(i) for i in range(21)]
    duplicate = deepcopy(points[4]);duplicate["imbalance"] = -.5
    assert causal_forecasts(points+[duplicate], cutoff=at(200)) == []
    points[4]["available_at"] = at(400)
    assert causal_forecasts(points, cutoff=at(200)) == []
    points[4] = point(4);points[4]["source_at"] = at(0)
    assert causal_forecasts(points, cutoff=at(200)) == []


def test_default_raw_evidence_gate_denies_and_verifier_error_never_becomes_truth():
    r = evaluate([row(1, 100)], verify=None)
    assert r["verified_unique_rows"] == 0
    assert r["rejections"] == {"independent_raw_source_replay_required": 1}
    def fail(_row):
        raise RuntimeError("CONTROLLED")
    assert evaluate([row(1, 100)], verify=fail)["rejections"] == {"raw_verifier_failed": 1}


def test_purge_and_parent_nonoverlap_apply_across_different_tokens():
    rows = [row(1, 100, event="shared"), row(2, 110, event="shared"),
            row(3, 250), row(4, 320), row(5, 390), row(6, 650),
            row(7, 790), row(8, 800, event="shared")]
    r = evaluate(rows)
    assert r["samples"] == {"training": 1, "validation": 1, "temporal_heldout": 2}
    assert r["rejections"]["overlapping_parent_episode"] == 1
    assert r["rejections"]["purged_boundary_or_crossing_label"] == 3
    assert r["overlapping_parent_groups"] == 1
    assert r["strict_event_disjoint_heldout_samples"] == 1


def test_temporal_same_parent_is_exploratory_not_independent_heldout():
    rows = [row(1, 100, event="shared"), row(2, 400, event="shared"), row(3, 800, event="shared")]
    r = evaluate(rows)
    assert r["comparisons"]["reversion20"]["temporal_heldout"]["mae"] == 0
    assert r["strict_event_disjoint_heldout_samples"] == 0
    assert r["reviewed_independent_groups"] == 0
    assert r["inference_status"] == "insufficient_independent_evidence"
    assert all(c["strict_event_disjoint_heldout"]["forecast_accuracy_inference"] is None
               for c in r["comparisons"].values())
    assert r["brier"] is None and r["log_loss"] is None
    assert not r["certification_authority"] and r["certification_heldout_events"] == 0


def test_insufficient_or_unreviewed_groups_withhold_ci_and_do_not_fake_zero_scores():
    for rows in ([row(i, 800+i*65, reviewed=True) for i in range(19)],
                 [row(i, 800+i*65, reviewed=False) for i in range(20)], []):
        r = evaluate(rows)
        assert r["multiple_testing"]["evaluated_hypotheses"] == 0
        assert r["comparisons"]["reversion20"]["strict_event_disjoint_heldout"]["forecast_accuracy_inference"] is None
    assert evaluate([])["comparisons"]["unchanged"]["temporal_heldout"]["mae"] is None


def test_reviewed_cluster_bootstrap_is_reproducible_and_holm_conservative():
    rows = [row(i, 800+i*65, reviewed=True) for i in range(20)]
    r, repeated = evaluate(rows), evaluate(rows)
    assert r == repeated
    inference = r["comparisons"]["reversion20"]["strict_event_disjoint_heldout"]["forecast_accuracy_inference"]
    assert inference["interval_95"] == pytest.approx([.1, .1])
    assert inference["parent_clusters"] == 20 and inference["supported_positive_effect"]
    assert inference["holm_adjusted_p"] >= inference["p_one_sided"]
    base = r["comparisons"]["unchanged"]["strict_event_disjoint_heldout"]["forecast_accuracy_inference"]
    assert base["p_one_sided"] == 1 and not base["supported_positive_effect"]
    assert r["model_promotion_authority"] is False


def test_planned_family_includes_missing_hypotheses_in_holm_multiplier():
    assert _holm({"only_one_evaluable": .01}) == {"only_one_evaluable": .08}
    assert _holm({"a": .01, "b": .02}) == {"a": .08, "b": .14}


def test_one_unreviewed_or_bad_review_proof_withholds_entire_inference():
    rows = [row(i, 800+i*65, reviewed=True) for i in range(20)]
    rows[-1]["independence_evidence_sha256"] = "not-a-proof"
    r = evaluate(rows)
    assert r["reviewed_independent_groups"] == 19
    assert r["multiple_testing"]["evaluated_hypotheses"] == 0


def test_selected_cost_performance_is_separate_from_forecast_skill_and_can_be_negative():
    rows = [row(1, 800)]
    rows[0]["costs"]["net_per_share"] = -.02
    rows[0]["estimated_edge_by_candidate"]["reversion20"] = .0299
    r = evaluate(rows)
    for name in ["reversion20", "momentum20"]:
        assert r["comparisons"][name]["temporal_heldout"]["mae"] == 0
    reversion = r["comparisons"]["reversion20"]["temporal_heldout"]["modeled_execution"]
    momentum = r["comparisons"]["momentum20"]["temporal_heldout"]["modeled_execution"]
    assert reversion["selected_examples"] == 0 and reversion["mean_net_per_share"] is None
    assert momentum["selected_examples"] == 1 and momentum["mean_net_per_share"] == -.02
    assert momentum["sequential_unit_share_drawdown"] == .02


def test_missing_execution_does_not_become_a_free_or_profitable_hypothetical_trade():
    rows = [row(1, 800)];rows[0]["costs"]["executable"] = False
    r = evaluate(rows)["comparisons"]["momentum20"]["temporal_heldout"]
    assert r["samples"] == 1 and r["modeled_execution"]["observed_roundtrip_examples"] == 0
    assert r["modeled_execution"]["mean_net_per_share"] is None


def test_wrong_target_and_future_late_labels_and_family_changes_fail_closed():
    rows = [row(i, 800+i*70) for i in range(5)]
    rows[0]["target_at"] = at(999)
    rows[1]["label_at"] = at(999)
    rows[2]["label_observed_at"] = at(9999)
    rows[3]["forecasts"]["selected_after_seeing_holdout"] = .9
    rows[4]["forecasts"]["unchanged"] = .8
    r = evaluate(rows)
    assert r["verified_unique_rows"] == 0 and sum(r["rejections"].values()) == 5


def test_conflicting_row_identity_quarantines_both_versions():
    a = row(1, 800);b = deepcopy(a);b["actual_bid"] = .6
    r = evaluate([a, b])
    assert r["verified_unique_rows"] == 0


def test_bounds_and_aware_ordered_cutoffs_are_enforced():
    with pytest.raises(ValueError, match="aware"):
        causal_forecasts([], cutoff=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="ordered"):
        evaluate_experiments([], training_end=at(300), validation_end=at(100), cutoff=at(500))
    with pytest.raises(ValueError, match="bounded"):
        causal_forecasts([{}]*20001, cutoff=at(500))


def test_observation_after_training_boundary_cannot_backdate_label_availability():
    r = row(1, 200)
    r["label_observed_at"] = at(350)
    result = evaluate([r])
    assert result["samples"]["training"] == 0
    assert result["rejections"]["purged_boundary_or_crossing_label"] == 1


def test_parent_episode_extends_until_late_label_knowledge_not_just_receipt():
    first = row(1, 100, event="shared")
    first["label_observed_at"] = at(220)
    second = row(2, 180, event="shared")
    result = evaluate([first, second])
    assert result["samples"]["training"] == 1
    assert result["rejections"]["overlapping_parent_episode"] == 1
