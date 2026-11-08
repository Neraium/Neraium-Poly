"""Controlled independent target/event-group aggregation, no authentic outcomes."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase31.scoring import evaluate_domains, verify_event
from test_phase27_findings import NOW


def label(*,domain='crypto',market='m',token='t',p=.8,y=1,model='model',group='event'):
    f={'id':market+token,'domain':domain,'market_id':market,'token_id':token,'rules_sha256':'a'*64,
        'model_id':model,'timestamp':NOW.isoformat(),'event_end_time':(NOW+timedelta(hours=4)).isoformat(),'probability':p}
    proof={'event_result_verified':True,'native_payout_verified':False,'trading_authority':False,'certification_authority':False,
        'market_id':market,'token_id':token,'forecast_id':f['id'],'event_group_id':group,'outcome':y,
        'event_end_lower':(NOW+timedelta(hours=1)).isoformat(),'market_baseline_comparable':False}
    return {'label_id':market+token,'forecast':f,'forecast_available_at':NOW.isoformat(),'proof':proof}


def test_multiple_thresholds_count_one_event_and_equal_event_weights():
    a=label(p=.8);b=label(market='second',p=.2);c=label(market='third',p=.9,group='another')
    r=evaluate_domains([a,b,c]);m=r['models'][0]
    assert r['distinct_official_event_groups']==2 and m['event_disjoint_groups']==2
    assert m['descriptive_brier']==pytest.approx((((.8-1)**2+(.2-1)**2)/2+(.9-1)**2)/2)
    assert not r['statistical_independence_verified'] and r['effective_independent_sample_size'] is None
    assert m['market_baseline_comparison'] is None and not m['superiority_established']


def test_early_absorbing_event_can_score_only_after_prospective_publication():
    a=label();r=evaluate_domains([a]);assert r['verified_forecast_labels']==1
    late=deepcopy(a);late['forecast_available_at']=late['proof']['event_end_lower']
    assert evaluate_domains([late])['verified_forecast_labels']==0


def test_nhl_forecast_must_precede_start_not_just_completion():
    a=label(domain='sports');a['forecast_available_at']=(NOW+timedelta(hours=4)).isoformat()
    assert evaluate_domains([a])['verified_forecast_labels']==0


def test_earliest_exact_target_is_frozen_and_boundary_losses_not_hidden():
    a=label(p=0);later=deepcopy(a);later['forecast']['id']='later';later['proof']['forecast_id']='later';later['forecast']['timestamp']=(NOW+timedelta(seconds=1)).isoformat();later['forecast_available_at']=later['forecast']['timestamp'];later['forecast']['probability']=1.
    r=evaluate_domains([later,a]);m=r['models'][0]
    assert m['descriptive_brier']==1 and m['descriptive_log_loss'] is None
    assert m['event_scores'][0]['forecast_id']==a['forecast']['id']


async def test_unlicensed_crypto_router_never_acquires_or_labels(tmp_path):
    result=await verify_event(label()['forecast'],directory=tmp_path,clock=lambda:NOW)
    assert not result.get('event_result_verified') and result['native_payout_verified'] is False
    assert not list(tmp_path.iterdir())
