"""Controlled chronology/provenance cases; these are never genuine market results."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase35.validation import (
    audit_market_baselines,
    conditional_native_bounds,
    validate_native_market_rows,
)
from test_phase16_readiness import BOUNDARY, CUTOFF, START, row
from test_phase24_weather_economics import NOW, book, market


def original():
    m=market();b=book(m).model_dump(mode='json')
    f={'id':'CONTROLLED-FORECAST','timestamp':NOW.isoformat(),'evidence_cutoff':NOW.isoformat(),
       'event_end_time':m.end_time.isoformat(),'market':m.model_dump(mode='json'),'book':b,
       'market_id':m.market_id,'event_id':m.event_id,'token_id':m.token_id,'book_id':b['id'],
       'book_sha256':digest(b),'rules_sha256':sha256(m.resolution_rules.encode()).hexdigest(),
       'market_expected_payout':.41,'market_probability':None,'probability':.6,
       'lower_probability':0,'upper_probability':1,'domain':'weather','model_id':'CONTROLLED',
       'model_version':'fixture-v1','model_sha256':'1'*64,'conditioning':'routine reference completion',
       'probability_semantics':'binary_event_probability','unconditional_contract_probability':False}
    s={'id':'CONTROLLED-STUDY','available_at':NOW.isoformat(),'forecasts':[f],
       'trading_authority':False,'certification_authority':False}
    return {'study':s,'forecast':f}


def replay(s,f,**kwargs):
    return {'verified':True,'forecast_sha256':digest(f),'original_study_sha256':digest(s)}


def audit(items,**kwargs):
    return audit_market_baselines(items,as_of=NOW+timedelta(seconds=3),forecast_verifier=kwargs.pop('forecast_verifier',replay),**kwargs)


def test_preserved_original_market_quote_never_becomes_conditional_target_comparison():
    item=original();before=deepcopy(item);r=audit([item]);b=r['baselines'][0]
    assert item==before and r['exact_original_market_baselines']==1
    assert b['market_expected_payout_midpoint']==pytest.approx(.41)
    assert b['native_sensitivity']['native_expected_payout_interval']==[0,1]
    assert r['native_semantics_comparable_forecasts']==r['native_verified_pairs']==0
    assert b['paired_brier'] is None and r['models'][0]['rank'] is None
    assert not r['trading_authority'] and not r['certification_authority']


def test_total_probability_bounds_are_sensitivity_not_calibrated_confidence():
    r=conditional_native_bounds([.6,.7],condition_probability_interval=[.9,1])
    assert r['native_expected_payout_interval']==pytest.approx([.54,.73])
    assert r['interval_status']=='assumption_sensitivity_not_confidence_interval'
    assert not r['ex_ante_condition_evidence_verified'] and not r['qualified_opportunity']
    for values in ([float('nan'),1],[.8,.2],[False,1]):
        with pytest.raises(ValueError):conditional_native_bounds(values)


@pytest.mark.parametrize('fault',['quote','identity','hash','future_book','stale_book','future_cutoff','membership','model_replay'])
def test_quote_and_model_provenance_fail_closed(fault):
    item=original();f=item['forecast']
    if fault=='quote':f['market_expected_payout']=.42
    elif fault=='identity':f['token_id']='WRONG'
    elif fault=='hash':f['book']['asks'][0]['size']=99
    elif fault in ('future_book','stale_book'):
        stamp=(NOW+timedelta(seconds=1 if fault=='future_book' else -16)).isoformat()
        f['book'].update(timestamp=stamp,available_at=stamp);f['book_sha256']=digest(f['book'])
    elif fault=='future_cutoff':f['evidence_cutoff']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='membership':item['study']['forecasts']=[]
    r=audit([item],forecast_verifier=None if fault=='model_replay' else replay)
    assert not r['baselines'] and r['rejections'] and r['metrics'] is None


def test_original_identity_dedup_preserves_earliest_and_quarantines_conflicts():
    a=original();b=deepcopy(a);b['study']['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    r=audit([b,a]);assert r['exact_original_market_baselines']==1
    assert r['baselines'][0]['recorded_at']==NOW.isoformat()
    b['forecast']['probability']=.7
    r=audit([a,b]);assert r['exact_original_market_baselines']==0
    assert 'conflicting_original_forecast_identity' in r['rejections']


def native(i=0,split='train'):
    r=row(i,split);m=market();b=book(m).model_dump(mode='json')
    b.update(market_id=r['market_id'],token_id=r['token_id'],timestamp=r['market_at'],available_at=r['market_available_at'])
    b['bids'][0]['price']=.49;b['asks'][0]['price']=.51
    r.update(market_book=b,market_book_sha256=digest(b),native_payout_verified=True,
             unconditional_contract_probability=True,split_declared_at=(START-timedelta(days=2)).isoformat())
    return r


def validate(rows,verify_row=lambda _:True):
    return validate_native_market_rows(rows,training_end=BOUNDARY-timedelta(days=2),
        heldout_start=BOUNDARY,as_of=CUTOFF,verify_row=verify_row)


def test_small_native_cohort_withholds_scores_and_preserves_certification_gate():
    r=validate([native()]);c=r['cohorts'][0]['calibration']
    assert c['training_events']==1 and c['heldout_events']==0 and c['metrics'] is None
    assert r['required_training_events']==r['required_heldout_events']==100
    assert r['execution_cost_adjusted_performance'] is None
    assert not r['trading_authority'] and not r['certification_authority']


@pytest.mark.parametrize('fault',['conditional','no_native_proof','later_split','wrong_book','changed_midpoint','missing_replay'])
def test_native_flags_cannot_substitute_for_causal_raw_replay(fault):
    r=native(0,'heldout')
    if fault=='conditional':r['conditioning']='completed only'
    elif fault=='no_native_proof':r['native_payout_verified']=False
    elif fault=='later_split':r['split_declared_at']=(BOUNDARY+timedelta(days=1)).isoformat()
    elif fault=='wrong_book':r['market_book']['token_id']='WRONG'
    elif fault=='changed_midpoint':r['market_probability']=.51
    result=validate([r],verify_row=None if fault=='missing_replay' else lambda _:True)
    assert result['raw_replayed_rows']==0 and not result['cohorts'] and result['rejections']


def test_native_comparison_is_event_disjoint_and_multiple_testing_adjusted():
    rows=[native(i,split) for split in ('train','heldout') for i in range(100)]
    other=deepcopy(rows)
    for r in other:r['model_version']='CONTROLLED-CHALLENGER';r['model_sha256']='a'*64
    result=validate(rows+other)
    assert result['multiple_testing_cohorts']==2
    for c in result['cohorts']:
        cal=c['calibration'];m=cal['metrics']
        assert cal['training_events']==cal['heldout_events']==100
        assert m['brier']==pytest.approx(.04) and m['market_brier']==.25
        assert m['paired_brier_difference_95_bound'][1]>.07
        assert 'Bonferroni' in m['interval_method'] and not m['forecasting_superiority_supported']
        assert m['trading_advantage'] is None


def test_parent_overlap_excludes_both_training_and_heldout():
    a,b=native(),native(0,'heldout');b.update(event_id=a['event_id'],dependency_group=a['dependency_group'])
    r=validate([a,b]);assert not r['cohorts'] and len(r['cross_split_groups'])==1


def test_verifier_faults_are_explicit_without_interrupting_inventory():
    def broken(*args,**kwargs):raise RuntimeError('controlled unavailable source')
    r=audit([original()],forecast_verifier=broken)
    assert r['rejections']=={'original_model_replay_failed':1} and not r['baselines']
    def forged(s,f,**kwargs):return {**replay(s,f),'original_study_sha256':'0'*64}
    assert not audit([original()],forecast_verifier=forged)['baselines']


def test_native_semantics_without_resolved_labels_do_not_create_scores_or_rank():
    item=original();f=item['forecast']
    f.update(conditioning=None,unconditional_contract_probability=True,market_probability=.41)
    r=audit([item])
    assert r['native_semantics_comparable_forecasts']==1 and r['native_verified_pairs']==0
    assert r['models'][0]['rank'] is None and r['metrics'] is None
    assert not r['trading_authority']


def finalized_item():
    item=original();f=item['forecast'];f['contract']={'station':'ZUCK','day':'2026-11-08'}
    item['proof']={'native_payout_verified':True,'proof_status':'rpc_corroborated_finalized_ctf_resolution',
        'market_id':f['market_id'],'event_id':f['event_id'],'rules_sha256':f['rules_sha256'],
        'forecast_sha256':digest(f),'token_ids':['Yes','No'],'payouts':[0,1],
        'settlement_at':(NOW+timedelta(hours=14)).isoformat(),
        'available_at':(NOW+timedelta(hours=15)).isoformat(),
        'trading_authority':False,'certification_authority':False}
    return item


def native_report(items,**kwargs):
    from neraium_poly.research.phase35.validation import native_market_baseline_report
    return native_market_baseline_report(items,as_of=NOW+timedelta(days=2),forecast_verifier=replay,
        native_verifier=kwargs.pop('native_verifier',lambda item,**_:item['proof']),**kwargs)


def test_descriptive_native_market_scores_do_not_relabel_conditional_models():
    item=finalized_item();before=deepcopy(item);r=native_report([item]);d=r['domains'][0]
    assert item==before and r['native_event_groups']==r['scored_native_market_targets']==1
    assert d['descriptive_native_market_brier']==pytest.approx(.41**2)
    import math
    assert d['descriptive_native_market_log_loss']==pytest.approx(-math.log(.59))
    assert r['conditional_model_forecasts']==1 and r['model_vs_native_market_scores'] is None
    assert r['confidence_intervals'] is None and r['realized_simulated_pnl'] is None
    assert r['certified_training_events']==r['certified_heldout_events']==0
    assert not r['trading_authority'] and not r['certification_authority']


@pytest.mark.parametrize('fault',['missing_replay','proof_hash','token','rules','future_settlement','late_publication','fractional'])
def test_native_market_scoring_rejects_unbound_or_noncausal_outcomes(fault):
    item=finalized_item();p=item['proof']
    if fault=='proof_hash':p['forecast_sha256']='0'*64
    elif fault=='token':p['token_ids']=['OTHER','No']
    elif fault=='rules':p['rules_sha256']='0'*64
    elif fault=='future_settlement':p['settlement_at']=(NOW+timedelta(days=3)).isoformat()
    elif fault=='late_publication':item['study']['available_at']=(NOW+timedelta(hours=14)).isoformat()
    elif fault=='fractional':p['payouts']=[1,1]
    r=native_report([item],native_verifier=None if fault=='missing_replay' else lambda item,**_:item['proof'])
    assert not r['domains'] and not r['native_event_groups'] and r['rejections']


def test_same_parent_station_day_and_multiple_models_do_not_inflate_native_samples():
    a=finalized_item();b=deepcopy(a)
    b['forecast']['id']='CONTROLLED-ALTERNATIVE';b['forecast']['model_id']='CONTROLLED-ALTERNATIVE'
    b['proof']['forecast_sha256']=digest(b['forecast'])
    r=native_report([a,a,b]);assert r['exact_original_forecasts_with_native_proof']==2
    assert r['scored_native_market_targets']==r['native_event_groups']==1
    assert r['rejections']['repeated_native_forecast_not_independent']==1
    assert r['conditional_model_forecasts']==2


def test_parent_aliases_share_one_station_day_but_inconsistent_day_binding_quarantines():
    a=finalized_item();b=deepcopy(a);f=b['forecast'];f['id']='CONTROLLED-OTHER'
    f['market']['event_id']=f['event_id']='CONTROLLED-parent-alias'
    b['proof'].update(event_id=f['event_id'],forecast_sha256=digest(f))
    r=native_report([a,b]);assert r['native_event_groups']==1
    f['event_id']=f['market']['event_id']=a['forecast']['event_id'];f['contract']['day']='2026-11-09'
    b['proof'].update(event_id=f['event_id'],forecast_sha256=digest(f))
    r=native_report([a,b]);assert r['native_event_groups']==0
    assert r['rejections']['native_parent_has_inconsistent_station_day_groups']==2


def test_native_replay_failure_is_bounded_and_never_scores():
    def broken(*args,**kwargs):raise RuntimeError('controlled RPC unavailable')
    r=native_report([finalized_item()],native_verifier=broken)
    assert r['rejections']=={'native_source_replay_failed':1}
    assert r['native_event_groups']==0
