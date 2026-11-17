"""Focused causal/isolation controls and replay of authentic finalized SPX proof."""
import asyncio
import copy
import json
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from neraium_poly.research.phase44.cohort import Cohort, opportunities
from neraium_poly.research.phase44.metrics import scores
from neraium_poly.research.phase44.native import replay, verify
from neraium_poly.research.phase44.outcomes import rebind
from neraium_poly.research.phase44.reference import ReferenceSampler
from test_phase42_strategies import frame_at
from test_phase42_strategies import setup as _setup

setup=_setup
PROOF=Path(__file__).resolve().parents[1]/'.planning/evidence/phase44/native-spx2'


def test_reference_reader_failure_and_age_invalidate_without_fallback(setup):
    _x,clock,_m,b,_f,frame,_fees,_store,_risk=setup
    sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame',clock=lambda:clock[0],reader=lambda _:frame_at(frame,b,clock[0]).model_copy(update={'source':'neraium-poly/public-market-frame/v1','producer_health':{'status':'ok','live_trading_enabled':False}}))
    sampler.observe();assert sampler.latest().books and sampler.status()['status']=='fresh'
    clock[0]+=timedelta(seconds=16)
    with pytest.raises(ValueError):sampler.latest()
    def fail(_):raise httpx.ReadTimeout('CONTROLLED')
    sampler.reader=fail;sampler.observe()
    assert sampler.frame is None and sampler.status()['failures']==1
    with pytest.raises(ValueError):sampler.latest()


async def test_slow_reference_reader_does_not_block_loop_and_shutdown_drains(setup):
    _x,clock,_m,b,_f,frame,_fees,_store,_risk=setup;calls=[];done=[]
    def read(_):
        calls.append(True);time.sleep(.08);done.append(True);return frame_at(frame,b,clock[0]).model_copy(update={'source':'neraium-poly/public-market-frame/v1','producer_health':{'status':'ok','live_trading_enabled':False}})
    sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame',clock=lambda:clock[0],reader=read)
    task=asyncio.create_task(sampler.run(lambda:False));start=time.monotonic();ticks=0
    while time.monotonic()-start<.04:await asyncio.sleep(.002);ticks+=1
    assert ticks>=5 and not done
    sampler.stop();await task
    assert done==[True] and calls==[True] and sampler.latest().books


def test_new_cohort_preserves_previous_losses_stop_and_recovers_independently(setup):
    original,clock,_m,b,f,frame,fees,store,risk=setup
    original.state['profiles']['aggressive']['suspended']=True
    old=copy.deepcopy(original.state)
    cohort=Cohort(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    cohort.enroll([f],verifier=lambda _:None);cohort.step(frame,fees)
    clock[0]+=timedelta(seconds=1);cohort.step(frame_at(frame,b,clock[0]),fees)
    assert original.state==old and cohort.state['profiles']['aggressive']['positions']
    assert cohort.last['id'].startswith('strategy44:') and store.latest('StrategyCycle44',1)
    assert not any(p['strategy']=='spread_capture' for s in cohort.state['profiles'].values() for p in s['positions'].values())
    recovered=Cohort(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    assert recovered.state==cohort.state


def test_bid_repricing_ignores_midpoint_only_moves_and_requires_verified_round_trip(setup):
    _x,clock,m,b,_f,_frame,fees,_store,_risk=setup;now=clock[0]+timedelta(seconds=60)
    h={m.token_id:[{'at':(now-timedelta(seconds=v)).isoformat(),'mid':.5,'bid':.44} for v in (100,80,60)]}
    cs,_=opportunities({m.token_id:m},{m.token_id:b},{},h,{},fees,now)
    assert not any(c['strategy']=='momentum' for c in cs)
    h[m.token_id]=[{**v,'bid':.3} for v in h[m.token_id]]
    b=frame_at(_frame,b,now,size=200).books[0]
    cs,_=opportunities({m.token_id:m},{m.token_id:b},{},h,{},fees,now)
    assert any(c['strategy']=='momentum' and c['probability'] is None for c in cs)


def test_authentic_spx_proof_is_replayable_and_uses_finalized_chain_not_api_price():
    proof=replay(PROOF);assert proof['payout']==0 and proof['native_payout_verified']
    assert proof['resolved_at']=='2026-11-16T23:29:04+00:00'
    bundle=json.loads((PROOF/'bundle.json').read_bytes())
    bundle['gamma']['outcomePrices']='["1","0"]'
    assert verify(bundle)['payout']==0  # Terminal price is never the payout proof.
    for field in ('rules_sha256','token_id','event_id'):
        bad=copy.deepcopy(bundle);bad['forecast'][field]='CONTROLLED-bad'
        with pytest.raises((ValueError,KeyError)):verify(bad)
    bad=copy.deepcopy(bundle);bad['forecast']['timestamp']='2026-11-17T00:00:00+00:00'
    with pytest.raises(ValueError):verify(bad)
    bad=copy.deepcopy(bundle);bad['resolution_hint']['data'][0]['was_disputed']=True
    with pytest.raises(ValueError):verify(bad)


def test_rebind_same_native_event_keeps_forecasts_and_groups_separate():
    proof=replay(PROOF);bundle=json.loads((PROOF/'bundle.json').read_bytes());f=bundle['forecast']
    second={**f,'id':'CONTROLLED-second','model_id':'CONTROLLED-challenger'}
    rebound=rebind(proof,f,second);assert rebound['forecast_id']==second['id']
    stats=scores({f['id']:f,second['id']:second},{f['id']:proof,second['id']:rebound});assert len(stats)==2
    assert all(v['native_parent_groups']==1 and v['confidence_interval'] is None for v in stats.values())
    for v in stats.values():assert v['scores']['market']['brier']==pytest.approx(.235**2)
    future={**second,'timestamp':proof['resolved_at']}
    with pytest.raises(ValueError):rebind(proof,f,future)
    bad={**second,'rules_sha256':'bad'}
    with pytest.raises(ValueError):rebind(proof,f,bad)


def test_native_raw_evidence_tamper_is_rejected(tmp_path):
    import shutil
    local=tmp_path/'proof';shutil.copytree(PROOF,local)
    manifest=json.loads((local/'manifest.json').read_text());path=local/manifest['responses'][0]['response_path'];path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):replay(local)


def test_supplemental_merge_preserves_fresh_tokens_and_quarantines_conflicts(setup):
    from neraium_poly.research.phase44.reference import merge_supplemental
    _x,clock,m,b,_f,frame,_fees,_store,_risk=setup
    extra=m.model_copy(update={'token_id':'CONTROLLED-extra'});eb=b.model_copy(update={'token_id':extra.token_id})
    combined=merge_supplemental(frame,(extra,),(eb,),clock[0])
    assert extra.token_id in {v.token_id for v in combined.books}
    assert next(v for v in combined.books if v.token_id==extra.token_id).timestamp==eb.timestamp
    conflicting=m.model_copy(update={'event_id':'CONTROLLED-different'})
    combined=merge_supplemental(frame,(conflicting,),(b,),clock[0])
    assert not combined.books and combined.producer_health['supplemental_conflicts']==1
    with pytest.raises(ValueError):merge_supplemental(frame,(extra,),(eb,),clock[0]+timedelta(seconds=16))


def test_exit_fee_uses_current_verified_parameters_without_rewriting_entry(setup):
    engine,clock,m,_b,_f,_frame,fees,_store,_risk=setup
    p={'token_id':m.token_id,'rate':.1};fee={**fees[m.token_id],'rate':0.}
    used,known=engine.exit_fee(p,fee,clock[0]);assert known and used['rate']==0 and p['rate']==.1
    used,known=engine.exit_fee(p,fee,clock[0]+timedelta(seconds=301));assert not known and used['rate']==.1


def test_verified_forecast_scores_persist_even_without_shadow_positions(setup):
    engine,clock,m,_b,f,_frame,_fees,store,risk=setup
    assert not any(s['positions'] for s in engine.state['profiles'].values())
    clock[0]+=timedelta(seconds=2)
    proof={'forecast_id':f['id'],'event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,'rules_sha256':f['rules_sha256'],
        'payout':0,'resolved_at':(clock[0]-timedelta(seconds=1)).isoformat(),'available_at':clock[0].isoformat(),'verified':True,'native_payout_verified':True}
    assert engine.settle({f['id']:proof})
    recovered=type(engine)(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    assert recovered.state['labels'][f['id']]==proof
    assert recovered.report()['verified_outcomes']==1 and not recovered.settle({f['id']:proof})


def test_retired_cohort_drops_only_unheld_derived_depth_and_keeps_losses(setup):
    from neraium_poly.research.phase44.cohort import LegacyCohort
    engine,clock,m,_b,_f,frame,fees,store,risk=setup
    engine.state['profiles']['aggressive']['suspended']=True
    engine.state['profiles']['aggressive']['cash']=490.
    engine._commit(copy.deepcopy(engine.state),[],{'operation':'CONTROLLED loss history'})
    legacy=LegacyCohort(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    legacy.step(frame,fees)
    assert legacy.state['profiles']['aggressive']['cash']==490. and legacy.state['profiles']['aggressive']['suspended']
    assert not legacy.state['profiles']['aggressive']['books'] and not legacy.state['profiles']['aggressive']['credits']
    assert not any(s['orders'] for s in legacy.state['profiles'].values())
    assert m.market_id in legacy.state['markets_seen'] or m.token_id not in legacy.state['history']
