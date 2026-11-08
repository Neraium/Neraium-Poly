"""Controlled event-label tests, never reported as authentic evidence."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase26 import outcomes as native
from neraium_poly.research.phase30 import outcomes
from test_phase26_outcomes import ASOF, NOW, fixtures, install


async def verified(monkeypatch,tmp_path):
    _m,f,study,g,t,h=fixtures();calls=install(monkeypatch,g,t,h,final_proof=False)
    result=await outcomes.verify_official_event(f,directory=tmp_path,clock=lambda:ASOF)
    assert result['event_result_verified'] and result['status']=='official_event_verified'
    assert 'controlled-native-acquire' not in calls
    return f,study,result,calls


async def test_official_completed_event_scores_without_claiming_native_payout(monkeypatch,tmp_path):
    f,study,result,calls=await verified(monkeypatch,tmp_path)
    score=outcomes.replay_official_event(result,study,f,evidence_root=tmp_path,as_of=ASOF)
    assert score['event_result_verified'] and score['outcome']==1
    assert score['brier']==pytest.approx((f['probability']-1)**2)
    assert score['market_brier'] is None and score['market_log_loss'] is None
    assert not score['native_payout_verified'] and not score['market_baseline_comparable']
    assert not score['trading_authority'] and not score['certification_authority']
    assert score['event_end_lower']=='2026-11-08T03:12:00+00:00'
    assert len(calls)==3


@pytest.mark.parametrize('fault',['probability','foreign_study','native_flag','market_flag','authority','source_url','corrupt_raw','path_escape','future_receipt','wrong_winner','group','rules','target'])
async def test_event_label_replay_requires_exact_sources_target_and_prospectivity(monkeypatch,tmp_path,fault):
    f,study,result,_calls=await verified(monkeypatch,tmp_path)
    if fault=='probability':f={**f,'probability':.999};study={**study,'forecasts':[f]}
    elif fault=='foreign_study':study={**study,'forecasts':[]}
    elif fault=='native_flag':result['native_payout_verified']=True
    elif fault=='market_flag':result['market_baseline_comparable']=True
    elif fault=='authority':result['trading_authority']=True
    elif fault=='source_url':result['official_evidence'][0]['source_url']='https://example.com/'
    elif fault=='corrupt_raw':(tmp_path/result['evidence_directory']/result['official_evidence'][0]['raw_file']).write_bytes(b'corrupt controlled source')
    elif fault=='path_escape':result['official_evidence'][0]['raw_file']='../foreign'
    elif fault=='future_receipt':result['available_at']=(ASOF+timedelta(seconds=1)).isoformat()
    elif fault=='wrong_winner':result['official_result']['expected_payout']=0
    elif fault=='group':result['event_group_id']='unrelated'
    elif fault=='rules':result['rules_sha256']='f'*64
    elif fault=='target':result['target']='unconditional_native_payout'
    with pytest.raises((ValueError,KeyError,StopIteration)):
        outcomes.replay_official_event(result,study,f,evidence_root=tmp_path,as_of=ASOF)


async def test_nonfinal_noresult_or_unstarted_never_get_binary_event_label(monkeypatch,tmp_path):
    _m,f,_s,g,t,h=fixtures();g['data'][0]['gameStateId']=3;calls=install(monkeypatch,g,t,h)
    r=await outcomes.verify_official_event(f,directory=tmp_path,clock=lambda:ASOF)
    assert not r['event_result_verified'] and r['status']=='pending' and len(calls)==2
    r=await outcomes.verify_official_event(f,directory=tmp_path,clock=lambda:NOW)
    assert not r['event_result_verified'] and r['reason']=='official_game_not_started'
    r=await outcomes.verify_official_event({**f,'league':'NBA'},directory=tmp_path,clock=lambda:ASOF)
    assert not r['event_result_verified'] and 'NBA_source_access_unavailable' in r['reason']


async def test_native_gate_remains_blocked_on_same_official_result(monkeypatch,tmp_path):
    _m,f,_s,g,t,h=fixtures();install(monkeypatch,g,t,h,final_proof=False)
    old=await native.verify_sport_outcome(f,directory=tmp_path/'native',clock=lambda:ASOF)
    assert not old['verified'] and old['reason']=='native_finalized_settlement_proof_unavailable'
    new=await outcomes.verify_official_event(f,directory=tmp_path/'event',clock=lambda:ASOF)
    assert new['event_result_verified'] and not new['native_payout_verified']


async def test_official_event_group_deduplicates_models_for_identical_real_game(monkeypatch,tmp_path):
    _m,f,_study,g,t,h=fixtures();install(monkeypatch,g,t,h,final_proof=False)
    one=await outcomes.verify_official_event(f,directory=tmp_path,clock=lambda:ASOF)
    changed=deepcopy(f);changed['id']='controlled-second-model'
    two=await outcomes.verify_official_event(changed,directory=tmp_path,clock=lambda:ASOF)
    assert one['event_group_id']==two['event_group_id'] and one['forecast_id']!=two['forecast_id']
    assert one['evidence_directory']!=two['evidence_directory']


def test_official_schedule_disambiguates_historical_team_suffix_without_guessing():
    import json
    _m,f,_s,g,t,_h=fixtures()
    # A retired catalog identity shares the current club's suffix, but does not
    # appear in the official game at the exact forecast's scheduled date/time.
    t['data'].append({'id':999,'fullName':'Historical Toronto Maple Leafs','leagueId':133})
    r=native.select_game(json.dumps(g).encode(),json.dumps(t).encode(),f['contract']['parameters'],native.at(f['event_end_time']))
    assert r['status']=='final_candidate' and r['teams']['Maple Leafs']['id']==10
    # If two same-alias clubs really appear at this exact schedule, quarantine.
    other=deepcopy(g['data'][0]);other.update(id=2026020269,gameNumber=269,homeTeamId=999);g['data'].append(other);g['total']=2
    with pytest.raises(ValueError,match='unique_official_NHL_team_identity'):
        native.select_game(json.dumps(g).encode(),json.dumps(t).encode(),f['contract']['parameters'],native.at(f['event_end_time']))
