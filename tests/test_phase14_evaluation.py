"""Controlled cohorts verify grouping/provenance, never genuine model skill."""

from datetime import timedelta

from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase14.evaluation import evaluate_domain_forecasts
from test_phase14_ledger import NOW, records


def cohort(*, same_event=False, untrusted=False):
    fs, os = [], []
    for i in range(20):
        _m, b, _c, _e, f = records(token=str(i))
        if same_event:
            f = f.model_copy(update={"event_id": "same-parent", "dependency_group": "renamed-" + str(i)})
        if untrusted:
            raw = b.model_copy(update={"source": "https://fixture.invalid/book"}).model_dump(mode="json")
            f = f.model_copy(update={"contemporaneous_market": {**f.contemporaneous_market, "book": raw}})
        proof = {"CONTROLLED": i}
        o = VerifiedEventOutcome(
            id="o" + str(i),
            timestamp=NOW + timedelta(days=1),
            available_at=NOW + timedelta(days=1),
            source="CONTROLLED",
            event_id=f.event_id,
            market_id=f.market_id,
            token_id=f.token_id,
            payout=1,
            resolution_rules_sha256=f.rules_sha256,
            settled_at=NOW + timedelta(days=1),
            verification_source="CONTROLLED",
            proof_sha256=content_sha256(proof),
            verification=proof,
        )
        fs.append(f)
        os.append(o)
    return fs, os


def test_renamed_groups_cannot_multiply_same_event():
    f, o = cohort(same_event=True)
    r = evaluate_domain_forecasts(
        f,
        o,
        forecast_validator=lambda f: True,
        outcome_validator=lambda o: True,
        independence_validator=lambda f: True,
    )
    assert r["models"][0]["independent_events"] == 1 and r["models"][0]["brier"] is None
    assert r["rejections"]["correlated_or_repeated_event_group"] == 19


def test_direct_cohort_requires_authentic_baseline_and_model_replay():
    f, o = cohort(untrusted=True)
    r = evaluate_domain_forecasts(
        f,
        o,
        forecast_validator=lambda f: True,
        outcome_validator=lambda o: True,
        independence_validator=lambda f: True,
    )
    assert not r["models"] and r["rejections"]["original_comparable_book_required"] == 20
    r = evaluate_domain_forecasts(
        f, o, outcome_validator=lambda o: True, independence_validator=lambda f: True
    )
    assert r["rejections"]["original_forecast_model_replay_required"] == 20


def test_same_record_timestamp_paired_metrics_separate_from_certification():
    f, o = cohort()
    r = evaluate_domain_forecasts(
        f,
        o,
        forecast_validator=lambda f: True,
        outcome_validator=lambda o: True,
        independence_validator=lambda f: True,
    )
    assert r["models"][0]["independent_events"] == 20
    assert r["models"][0]["brier"] is not None
    assert r["certified_minimum_training_events"] == r["certified_minimum_heldout_events"] == 100
    assert not r["automatic_promotion"]
