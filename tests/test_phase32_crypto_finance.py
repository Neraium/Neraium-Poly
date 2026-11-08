"""Controlled identity/readiness fixtures; never live outcomes."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase32.crypto_finance import audit_crypto_finance, qualify_reference
from test_phase31_crypto import ASOF, original


def inputs():
    study,f=original()
    return study,f,{'type':'forecast','forecast_id':f['id'],'forecast':f,'source_id':study['id'],
        'source_study_sha256':digest(study),'forecast_sha256':digest(f),'replay_verified':True,
        'available_at':study['available_at'],'review':{'canonical_group_id':'CONTROLLED-group'}}


def test_reference_ambiguity_precedes_any_provider_or_license_access():
    _s,f,_r=inputs();r=qualify_reference(f,as_of=ASOF)
    assert r['category']=='RESOLUTION_REFERENCE_AMBIGUOUS' and not r['forecast_reference_admissible']
    assert 'spot_reference_rule_ambiguity_requires_review' in r['reasons']
    assert r['data_license_status']=='authorization_unconfirmed_default_closed'
    assert not r['event_result_verified'] and r['outcome'] is None


def test_rule_guard_cannot_be_bypassed_by_symbol_or_rule_hash_changes():
    _s,f,_r=inputs();f=deepcopy(f);f['market']['resolution_rules']+=' CONTROLLED changed'
    with pytest.raises(ValueError,match='original_exact_market_token_rule_binding_required'):qualify_reference(f,as_of=ASOF)


def test_correct_originals_are_preserved_and_duplicate_observations_not_new_events():
    s,_f,r=inputs();before=deepcopy(s);calls=[]
    def load(identity):calls.append(identity);return s
    out=audit_crypto_finance([r,r],source_loader=load,as_of=ASOF)
    assert out['forecasts']==1 and calls==[s['id']] and s==before
    assert out['categories']=={'RESOLUTION_REFERENCE_AMBIGUOUS':1}
    assert out['maturity']=={'mature_boundary':1} and out['event_groups_with_verified_outcomes']==0
    assert not out['trading_authority'] and not out['native_payout_verified']


@pytest.mark.parametrize('fault',['study_sha','forecast_sha','replay','publication','null_source','loader_failure'])
def test_unqualified_originals_cannot_reach_source_contract_evaluation(fault):
    s,_f,r=inputs()
    if fault=='study_sha':r['source_study_sha256']='CONTROLLED-bad'
    elif fault=='forecast_sha':r['forecast_sha256']='CONTROLLED-bad'
    elif fault=='replay':r['replay_verified']=False
    elif fault=='publication':r['available_at']=(ASOF+timedelta(seconds=1)).isoformat()
    def load(_identity):
        if fault=='null_source':return None
        if fault=='loader_failure':raise OSError('CONTROLLED missing archive')
        return s
    out=audit_crypto_finance([r],source_loader=load,as_of=ASOF)
    assert out['source_contract_quarantined']==1 and not out['rows'][0]['source_binding_verified']
    assert not out['event_result_verified']


def test_conflicting_forecasts_quarantined_without_reading_original_sources():
    _s,_f,r=inputs();other={**r,'forecast_sha256':'CONTROLLED-conflict'}
    out=audit_crypto_finance([r,other],source_loader=lambda _:pytest.fail('no source read for conflict'),as_of=ASOF)
    assert out['forecasts']==1 and out['categories']=={'CONFLICTING_FORECAST_IDENTITY':1}


def test_unreplayed_null_review_is_not_implicitly_qualified():
    s,_f,r=inputs();r.update(review=None,replay_verified=False)
    out=audit_crypto_finance([r],source_loader=lambda _:s,as_of=ASOF)
    assert out['source_contract_quarantined']==1


def test_finance_waits_for_exact_official_close_and_preserves_fractional_cases():
    from datetime import UTC, datetime

    from neraium_poly.research.phase25.finance import supports
    from test_phase25_finance_economics import NOW, market

    m=market();c=supports(m,cutoff=NOW)['contract']
    f={'domain':'finance','market':m.model_dump(mode='json'),'contract':c,'market_id':m.market_id,
        'event_id':m.event_id,'token_id':m.token_id,'rules_sha256':c['rules_sha256'],
        'timestamp':NOW.isoformat(),'evidence_cutoff':NOW.isoformat(),'event_end_time':c['period_end']}
    r=qualify_reference(f,as_of=ASOF)
    assert r['category']=='NOT_YET_MATURE' and r['market_baseline_comparison'] is None
    r=qualify_reference(f,as_of=datetime(2026,11,10,tzinfo=UTC))
    assert r['category']=='OFFICIAL_REFERENCE_RESULT_REQUIRED' and not r['event_result_verified']
    assert 'ties_no_trade_and_fallback_are_not_binary_labels' in r['reasons']
    assert not r['native_payout_verified'] and r['outcome'] is None


def test_thin_registry_reference_cannot_contradict_preserved_original():
    s,_f,r=inputs();r=deepcopy(r);r['forecast']['market_id']='CONTROLLED-wrong-market'
    out=audit_crypto_finance([r],source_loader=lambda _:s,as_of=ASOF)
    assert out['source_contract_quarantined']==1 and not out['rows'][0]['source_binding_verified']
