"""Controlled cross-domain relationship experiments; not actual market findings."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase14.relationships import UniversalRelationships, digest

START=datetime(2026,11,6,tzinfo=UTC)


def definition(**changes):
    return {"id":"CONTROLLED-weather-energy-v1","kind":"statistical_relationship",
            "left_id":"station-feature","right_id":"energy-contract","left_domain":"weather",
            "right_domain":"finance","relation_type":"linear_dependency","minimum_residual":.05,
            "review_actor":"CONTROLLED test reviewer","available_at":START.isoformat(), **changes}


def pair(i,x=None,y=None,**changes):
    at=START+timedelta(seconds=i*30)
    x = i/20 if x is None else x
    y = 2*x if y is None else y
    common={"timestamp":at.isoformat(),"available_at":at.isoformat(),"semantics":"numeric_feature",
            "kind":"external_evidence","source":"CONTROLLED fixture",
            "uncertainty":{"absolute_error_bound":.001}}
    rows=[{**common,"entity_id":"station-feature","domain":"weather","value":x,"evidence_sha256":digest([i,"x"])},
          {**common,"entity_id":"energy-contract","domain":"finance","value":y,"evidence_sha256":digest([i,"y"])}]
    rows[0].update(changes)
    return rows,at


def engine(**changes):
    return UniversalRelationships(definition_validator=lambda d:True,observation_validator=lambda o:True,**changes)


def warm(e,d=None):
    d=d or definition()
    for i in range(10):
        rows,now=pair(i)
        result=e.observe(d,rows,now=now)
        assert result["status"]=="warming_up"


def test_callbacks_default_deny_not_self_asserted_relation_or_evidence():
    rows,now=pair(0)
    result=UniversalRelationships().observe(definition(),rows,now=now)
    assert result["status"]=="withheld" and not result["executable_opportunity"]
    e=UniversalRelationships(definition_validator=lambda d:True)
    assert "provenance" in e.observe(definition(),rows,now=now)["reason"]
    assert not e.summary()["registered_relationships"]


def test_actual_joint_change_requires_baseline_persistence_and_preserves_provenance():
    e=engine();warm(e)
    baseline=e.checkpoint()["states"][definition()["id"]]["baseline_evidence"]
    found=[]
    for i in range(10,28):
        rows,now=pair(i,y=-i/10)
        result=e.observe(definition(),rows,now=now)
        if result["finding_new"]:found.append(result)
    assert len(found)==1
    f=found[0]
    assert f["domains"]==["weather","finance"]
    assert f["persistent"] and f["persistence_count"]>=3
    assert f["baseline_evidence_sha256"]==baseline
    assert f["current_window_evidence_sha256"]!=baseline
    assert not f["causality_verified"] and not f["forecast_improvement_verified"]
    assert f["statistical_significance"] is None and not f["executable_opportunity"]
    assert e.summary()["persistent_findings"]==1
    restored=engine();restored.restore(e.checkpoint())
    rows,now=pair(28,y=-2.8)
    assert not restored.observe(definition(),rows,now=now)["finding_new"]
    assert restored.summary()["persistent_findings"]==1


def test_single_excursion_is_not_a_persistent_structural_change():
    e=engine();warm(e)
    rows,now=pair(10,y=-3)
    result=e.observe(definition(),rows,now=now)
    assert not result["persistent"] and not result["finding_new"]
    assert e.summary()["persistent_findings"]==0


def test_no_joint_variation_never_invents_dependency():
    e=engine()
    for i in range(12):
        rows,now=pair(i,x=.5,y=.5)
        result=e.observe(definition(),rows,now=now)
    assert result["reason"]=="insufficient_joint_variation_for_relationship_baseline"
    assert e.summary()["persistent_findings"]==0


def test_duplicate_book_pair_cannot_add_persistence():
    e=engine();warm(e)
    rows,now=pair(10,y=-3)
    e.observe(definition(),rows,now=now)
    for row in rows:
        row["timestamp"]=row["available_at"]=(now+timedelta(seconds=1)).isoformat()
    assert e.observe(definition(),rows,now=now+timedelta(seconds=1))["reason"]=="duplicate_pair_does_not_add_persistence"


@pytest.mark.parametrize("change,reason", [
    ({"available_at":(START+timedelta(days=1)).isoformat()},"causal_identity"),
    ({"evidence_sha256":"not-a-hash"},"causal_identity"),
    ({"uncertainty":{}},"finite relationship"),
    ({"entity_id":"wrong"},"ambiguous_relationship"),
])
def test_future_missing_or_ambiguous_evidence_withholds(change,reason):
    e=engine();rows,now=pair(0,**change)
    result=e.observe(definition(),rows,now=now)
    assert result["status"]=="withheld" and reason in result["reason"]


def test_quote_freshness_cannot_be_relaxed_by_definition():
    e=engine();rows,now=pair(0,kind="market_quote")
    d=definition(left_max_age_seconds=3600,max_pair_skew_seconds=3600)
    assert e.observe(d,rows,now=now+timedelta(seconds=16))["reason"]=="stale_relationship_observation"


def test_future_definition_and_claim_promotion_withhold():
    e=engine();rows,now=pair(0)
    assert e.observe(definition(available_at=(START+timedelta(days=1)).isoformat()),rows,now=now)["reason"]=="future_relationship_definition"
    for kind in ("forecast_improvement","executable_opportunity"):
        result=e.observe(definition(kind=kind),rows,now=now)
        assert result["status"]=="withheld" and not result["executable_opportunity"]


def logical_definition(**changes):
    return definition(kind="logical_probability_constraint",relation_type="mutually_exclusive",
        left_rules_sha256="a"*64,right_rules_sha256="b"*64,underlying_event_id="CONTROLLED-event",
        settlement_window="CONTROLLED-same-window",logical_scope_reviewed=True,**changes)


def logical_pair(i,a=.7,b=.6):
    rows,now=pair(i,x=a,y=b)
    for index,row in enumerate(rows):
        row.update(semantics="binary_event_probability",rules_sha256=("a" if index==0 else "b")*64,
                   underlying_event_id="CONTROLLED-event",settlement_window="CONTROLLED-same-window")
    return rows,now


def test_logical_constraint_never_implies_executable_arbitrage():
    e=engine();d=logical_definition()
    for i in range(13):
        rows,now=logical_pair(i)
        result=e.observe(d,rows,now=now)
    assert result["persistent"] and result["finding_new"]
    assert result["classification"]=="reviewed_logical_constraint_violation"
    assert not result["executable_opportunity"] and "atomic" in result["execution_blocker"]


@pytest.mark.parametrize("change", [{"semantics":"expected_payout"},{"rules_sha256":"c"*64},
                                   {"underlying_event_id":"other"},{"settlement_window":"other"}])
def test_logical_mismatched_settlement_or_semantics_rejects_before_warmup(change):
    e=engine();rows,now=logical_pair(0);rows[0].update(change)
    result=e.observe(logical_definition(),rows,now=now)
    assert result["status"]=="withheld"
    assert not e.summary()["registered_relationships"]


def test_restart_rejects_corrupt_baseline_counter_or_reviewer():
    e=engine();warm(e);checkpoint=e.checkpoint()
    bad=deepcopy(checkpoint)
    bad["states"][definition()["id"]]["baseline_evidence"][0]="bad"
    with pytest.raises(ValueError):engine().restore(bad)
    bad=deepcopy(checkpoint);bad["findings"]=-1
    with pytest.raises(ValueError):engine().restore(bad)
    with pytest.raises(ValueError):UniversalRelationships().restore(checkpoint)
    assert e.checkpoint()==checkpoint


def test_unbounded_numeric_scale_fails_before_mutating_temporal_state():
    e=engine();rows,now=pair(0,x=1e200)
    result=e.observe(definition(),rows,now=now)
    assert result["status"]=="withheld" and "normalization" in result["reason"]
    assert not e.summary()["registered_relationships"]


def test_definition_datetime_is_normalized_without_lookahead_or_hash_instability():
    e=engine();rows,now=pair(0)
    assert e.observe(definition(available_at=START),rows,now=now)["status"]=="warming_up"
    checkpoint=e.checkpoint()
    assert checkpoint["states"][definition()["id"]]["definition"]["available_at"]==START.isoformat()


def test_provenance_callback_failure_never_authorizes_a_finding():
    def broken(_):
        raise RuntimeError("CONTROLLED unavailable evidence replay")
    e=UniversalRelationships(definition_validator=lambda _:True,observation_validator=broken)
    rows,now=pair(0)
    result=e.observe(definition(),rows,now=now)
    assert result["status"]=="withheld" and not result["executable_opportunity"]
    assert not e.summary()["registered_relationships"]
