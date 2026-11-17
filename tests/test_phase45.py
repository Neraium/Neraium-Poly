"""Focused isolated engineering controls; controlled fixtures are not returns."""
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
from neraium_poly.research.phase45.cohort import Explorer, opportunities
from neraium_poly.research.phase45.diagnostics import breakdown
from neraium_poly.research.phase45.panel import Panel
from test_phase42_strategies import frame_at
from test_phase42_strategies import setup as _setup

setup=_setup


async def test_fresh_cache_hits_cannot_starve_due_fee_requests_and_nonforecast_depth_is_eligible(setup):
    _,clock,m,b,_,frame,_,_,_=setup;calls=[]
    async def observe(t):calls.append(t)
    cache=AsyncBudgetResearchFeeCache(None,SimpleNamespace(observed_fee=observe),clock=lambda:clock[0],can_write=lambda:True)
    ms=[m.model_copy(update={'token_id':str(i),'market_id':'market-'+str(i)}) for i in range(4)]
    bs=[b.model_copy(update={'token_id':v.token_id,'market_id':v.market_id}) for v in ms]
    for i in ('0','1'):cache.observations[i]={'observed_at':clock[0].isoformat()}
    await cache.refresh(frame.model_copy(update={'markets':tuple(ms),'books':tuple(bs)}),forecast_tokens=[])
    assert calls==['2','3'] and len(cache.observations)<=32


def test_explorer_has_four_distinct_hypotheses_preserves_old_stop_and_bounded_capital(setup):
    old,clock,_,b,f,frame,fees,store,risk=setup
    old.state['profiles']['aggressive']['suspended']=True;snapshot=copy.deepcopy(old.state)
    e=Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    e.enroll([f],verifier=lambda _:None);e.step(frame,fees)
    assert len(e.definitions)==4 and old.state==snapshot
    assert not any(s['positions'] for s in e.state['profiles'].values())
    clock[0]+=timedelta(seconds=1);e.step(frame_at(frame,b,clock[0]),fees)
    assert e.state['profiles']['aggressive']['positions']
    for s in e.state['profiles'].values():assert e.exposure(s)<=20+1e-8
    assert Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True).state==e.state
    assert e.report()['actual_account_access'] is False


def test_diagnostics_preserve_historical_ambiguity_and_separate_fee_from_history():
    r=breakdown({'a:bid_history_and_verified_fees_required':4,'b:native_fee_unavailable':3,'c:three_causal_bid_history_observations_required':2})
    assert r['total']==9
    assert r['observations']=={'historically_ambiguous_evidence_or_economics':4,'missing_verified_fees':3,'missing_independent_evidence':2}


def test_non_yes_no_pair_requires_authoritative_membership_and_matching_rules(setup):
    _,clock,m,b,_,_,fees,_,_=setup
    a=m.model_copy(update={'outcome':'Up'});z=m.model_copy(update={'outcome':'Down','token_id':'OTHER'});bz=b.model_copy(update={'token_id':z.token_id})
    fs={a.token_id:{**fees[a.token_id],'condition_tokens':[a.token_id,z.token_id]},z.token_id:{**fees[a.token_id],'token_id':z.token_id,'condition_tokens':[a.token_id,z.token_id]}}
    cs,_=opportunities({a.token_id:a,z.token_id:z},{a.token_id:b,z.token_id:bz},{},{},{},fs,clock[0])
    pair=[c for c in cs if c['strategy']=='consistency'];assert len(pair)==2 and pair[0]['market']['outcome']=='Up'
    assert all(c['probability'] is None for c in pair)
    fs[z.token_id]['condition_tokens']=[z.token_id,'UNRELATED']
    cs,rs=opportunities({a.token_id:a,z.token_id:z},{a.token_id:b,z.token_id:bz},{},{},{},fs,clock[0])
    assert not any(c['strategy']=='consistency' for c in cs) and any(r['reason']=='authoritative_condition_token_membership_missing' for r in rs)


def test_future_or_stale_forecasts_cannot_register_market_blend_and_original_is_immutable(setup):
    _,clock,_,b,f,frame,_,store,_=setup
    p=Panel(store,lambda:clock[0],lambda:True);original=copy.deepcopy(f)
    p.register({f['id']:f},frame);assert len(p.rows)==1 and f==original
    row=next(iter(p.rows.values()));assert row['probabilities']['blend_external25']==pytest.approx(.25*f['probability']+.75*.455)
    clock[0]+=timedelta(seconds=1);p.register({f['id']:f},frame_at(frame,b,clock[0]));assert len(p.rows)==1
    assert Panel(store,lambda:clock[0],lambda:True).rows==p.rows
    assert p.report({})['native_labeled_panels']==0 and p.report({})['scores_equal_parent_weight']=={}
    future={**f,'token_id':'other','id':'future','timestamp':(clock[0]+timedelta(seconds=1)).isoformat()}
    p.register({'future':future},frame);assert len(p.rows)==1


def test_panel_requires_exact_native_identity_and_forecast_before_resolution(setup):
    _,clock,m,_,f,frame,_,store,_=setup;p=Panel(store,lambda:clock[0],lambda:True);p.register({f['id']:f},frame)
    proof={'native_payout_verified':True,'payout':0,'market_id':m.market_id,'token_id':m.token_id,'event_id':m.event_id,'resolved_at':(clock[0]+timedelta(seconds=1)).isoformat()}
    r=p.report({f['id']:proof});assert r['native_parent_groups']==1 and r['confidence_interval'] is None
    assert r['scores_equal_parent_weight']['market']['brier']==pytest.approx(.455**2)
    assert p.report({f['id']:{**proof,'token_id':'UNRELATED'}})['native_labeled_panels']==0
    assert p.report({f['id']:{**proof,'resolved_at':clock[0].isoformat()}})['native_labeled_panels']==0


def test_economic_diagnostics_are_persisted_not_fills_and_native_min_is_separate(setup):
    _,clock,_m,_b,f,frame,fees,store,risk=setup
    e=Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    e.enroll([f],verifier=lambda _:None);e.step(frame,fees)
    r=e.report();assert r['economic_candidates']
    assert all(not v['actual_fill'] and not v['all_in_costs_verified'] for v in r['economic_candidates'])
    assert any(v['estimated_net_profit']>0 for v in r['economic_candidates'])
    recovered=Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    assert recovered.report()['economic_candidates']==r['economic_candidates']


def test_panel_withholds_nonpublic_and_stale_books(setup):
    _,clock,_m,b,f,frame,_,store,_=setup;p=Panel(store,lambda:clock[0],lambda:True)
    bad=frame.model_copy(update={'books':(b.model_copy(update={'source':'unsupported'}),)})
    p.register({f['id']:f},bad);assert not p.rows
    clock[0]+=timedelta(seconds=16);p.register({f['id']:f},frame);assert not p.rows


def test_native_hold_explorer_uses_principal_budget_not_immediate_roundtrip_veto(setup):
    old,clock,_m,b,f,frame,fees,store,risk=setup
    sample=frame_at(frame,b,clock[0],bid=.03,ask=.04,size=1000)
    e=Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    e.enroll([f],verifier=lambda _:None);e.step(sample,fees)
    assert e.state['profiles']['aggressive']['orders']
    assert all(o['exit_policy']=='native_hold45' for o in e.state['profiles']['aggressive']['orders'].values())
    clock[0]+=timedelta(seconds=1);e.step(frame_at(frame,b,clock[0],bid=.03,ask=.04,size=1000),fees)
    positions=copy.deepcopy(e.state['profiles']['aggressive']['positions']);assert positions
    clock[0]+=timedelta(seconds=301);e.step(frame_at(frame,b,clock[0],bid=.01,ask=.04,size=1000),fees)
    assert set(e.state['profiles']['aggressive']['positions'])==set(positions)
    assert not e.state['profiles']['aggressive']['closed'] and e.exposure(e.state['profiles']['aggressive'])<=20
    assert old.native_hold_research is False


def test_uncalibrated_positive_central_estimate_is_not_positive_conservative_profit(setup):
    from neraium_poly.research.phase45.economics import evaluate
    _,clock,m,b,f,_,fees,_,_=setup
    c={'strategy':'independent','token_id':m.token_id,'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),'target':f['probability'],'probability':f['probability'],'forecast':{**f,'lower_probability':0},'evidence_kind':'controlled','decision_fee':fees[m.token_id]}
    row=evaluate([c],Explorer.profile_configs,clock[0])[0]
    assert row['estimated_net_profit']>0 and row['uncertainty_lower_net_profit']<0
    assert not row['actual_fill'] and not row['trading_authority']


def test_pricing_contract_settlement_does_not_invent_probability_forecasts(setup):
    from neraium_poly.research.phase45.native_positions import capture, due
    _,clock,m,b,_,frame,fees,store,risk=setup
    e=Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    c={'created_at':clock[0].isoformat(),'market':m.model_dump(mode='json')}
    capture(e.state,[{'type':'shadow_intent','candidate':c}]);contract=next(iter(e.state['pricing_contracts45'].values()))
    assert contract['probability'] is None and not e.state['forecasts']
    assert due(e,clock[0])=={}
    # Isolated controlled position, not a claimed market fill or performance.
    profile=e.state['profiles']['aggressive'];profile['cash']-=2
    profile['positions']['CONTROLLED']={'market_id':m.market_id,'event_id':m.event_id,'token_id':m.token_id,'market':m.model_dump(mode='json'),'last_fill_at':clock[0].isoformat(),'quantity':5.,'cost':2.,'strategy':'consistency'}
    clock[0]+=timedelta(seconds=2)
    proof={k:contract[k] for k in ('market_id','event_id','token_id','rules_sha256')};proof.update(forecast_id=contract['id'],native_payout_verified=True,verified=True,payout=1,resolved_at=(clock[0]-timedelta(seconds=1)).isoformat(),available_at=clock[0].isoformat())
    with pytest.raises(ValueError):e.settle({contract['id']:{**proof,'token_id':'wrong'}})
    e.settle({contract['id']:proof});assert e.state['profiles']['aggressive']['cash']==503
    assert e.report()['forecasts']==0 and e.report()['native_pricing_contracts']['verified']==1
    assert not e.settle({contract['id']:proof}) and e.state['profiles']['aggressive']['cash']==503
    clock[0]+=timedelta(seconds=1);e.step(frame_at(frame,b,clock[0]),fees)
    assert Explorer(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True).state==e.state
