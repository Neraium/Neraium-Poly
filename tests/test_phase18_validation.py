"""Controlled parent-separation fixtures; no fixture is a genuine resolved event."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase18.validation import event_disjoint_validation
from test_phase16_readiness import BOUNDARY, CUTOFF, START, row


def evaluate(rows, **kw):
    return event_disjoint_validation(rows,training_end=BOUNDARY-timedelta(days=2),
        heldout_start=BOUNDARY,cutoff=CUTOFF,**kw)


def test_authenticity_default_denies_and_scores_remain_null():
    r=evaluate([row()]);assert r['rejections']=={'independent_forecast_outcome_replay_required':1}
    assert r['metrics'] is None and not r['cohorts']
    assert r['required_training_events']==r['required_heldout_events']==100
    assert not r['trading_authority'] and not r['certification_authority']


def test_parent_aliases_cannot_inflate_independent_heldout_groups():
    a,b=row(),row(0,'heldout');b['event_id']=a['event_id']
    r=evaluate([a,b],verify_row=lambda _r:True)
    assert r['ambiguous_parent_ids']==[a['event_id']]
    assert not r['cohorts'] and r['rejections']['same_parent_has_inconsistent_dependency_groups']==2


def test_validation_parent_never_becomes_heldout_even_if_training_excluded():
    v=row(199);v['split']='train';h=row(1,'heldout');h['dependency_group']=v['dependency_group'];h['event_id']=v['event_id']
    r=evaluate([v,h],verify_row=lambda _r:True)
    assert r['cross_split_groups']==[v['dependency_group']] and not r['cohorts']


def test_verified_independent_chronology_preserves100_100_certification_gate():
    rows=[row(i) for i in range(100)]+[row(i,'heldout') for i in range(100)]
    r=evaluate(rows,verify_row=lambda _r:True);c=r['cohorts'][0]['calibration']
    assert c['training_events']==c['heldout_events']==100 and c['cohort_sufficient']
    assert c['metrics']['brier']==pytest.approx(.04)
    assert not c['certification_authority'] and not c['metrics']['forecasting_superiority_supported']


def test_late_training_labels_and_future_or_changed_outcomes_withheld():
    a=row();a['outcome_available_at']=(BOUNDARY-timedelta(days=1)).isoformat()
    r=evaluate([a],verify_row=lambda _r:True)
    assert r['training_labels_late']==1 and not r['cohorts']
    b=row(0,'heldout');b['outcome_rules_sha256']='0'*64
    r=evaluate([b],verify_row=lambda _r:True)
    c=r['cohorts'][0]['calibration'];assert c['metrics'] is None and c['heldout_events']==0
    assert 'outcome_resolution_rules_mismatch' in c['rejections']


def test_domain_models_are_separated_and_repeated_forecasts_are_one_group():
    a,b=row(0,'heldout'),row(1,'heldout');b['domain']='other-controlled-domain'
    repeated=deepcopy(a);repeated['forecast_id']='controlled-repeat'
    r=evaluate([a,b,repeated],verify_row=lambda _r:True)
    assert len(r['cohorts'])==2
    assert sum(x['calibration']['heldout_events'] for x in r['cohorts'])==2
    assert all(x['calibration']['metrics'] is None for x in r['cohorts'])


def test_byte_boundaries_and_awareness_reject():
    with pytest.raises(ValueError,match='bytes'):evaluate([{'huge':'x'*300000}])
    with pytest.raises(ValueError,match='aware'):event_disjoint_validation([],training_end=START.replace(tzinfo=None),heldout_start=BOUNDARY,cutoff=CUTOFF)
