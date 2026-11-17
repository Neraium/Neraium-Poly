"""Small isolated execution controls, not market-performance evidence."""
import copy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase43 import economics, tournament
from test_phase42_strategies import events, frame_at
from test_phase42_strategies import setup as _setup

setup = _setup


def test_zero_credit_compaction_preserves_consumed_depth_after_recovery(setup):
    x,clock,_m,b,_f,frame,fees,store,risk=setup
    x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],size=10),fees)
    before=copy.deepcopy(x.state['profiles']['balanced']);s=x.state['profiles']['balanced']
    s['credits']['expired|bids|0.1']=0.;s['credits']['expired|asks|0.2']=0.
    x._commit(copy.deepcopy(x.state),[],{'operation':'CONTROLLED compaction'})
    assert all(v>0 for v in x.state['profiles']['balanced']['credits'].values())
    recovered=type(x)(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    clock[0]+=timedelta(seconds=1);recovered.step(frame_at(frame,b,clock[0],size=10),fees)
    assert recovered.state['profiles']['balanced']['cash']==before['cash']
    assert {k:{f:v for f,v in p.items() if f!='marked_book_at'} for k,p in recovered.state['profiles']['balanced']['positions'].items()}=={k:{f:v for f,v in p.items() if f!='marked_book_at'} for k,p in before['positions'].items()}


def test_settlement_horizon_does_not_force_five_minute_liquidation(setup):
    x,clock,_m,b,_f,frame,fees,_store,_risk=setup
    x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees)
    clock[0]+=timedelta(seconds=301);x.step(frame_at(frame,b,clock[0]),fees)
    p=x.state['profiles']['balanced']['positions'];assert p
    assert all(v['exit_policy']=='settlement_aligned_v43' for v in p.values())
    assert not x.state['profiles']['balanced']['closed']
    t=x.report()['exit_tournament'];assert t['arms']['hold_native']['verified_settlement_pnl']==0
    assert t['arms']['hold_native']['open_lots']>0
    assert t['arms']['time_300s']['modeled_exit_pnl']<0
    assert t['arms']['first_executable_bid']['modeled_exit_pnl']<0
    assert t['arms']['evidence_repricing']['closed_lots']==0


def test_matched_exits_share_entries_and_partial_depth_and_preserve_native_proof_gate(setup):
    x,clock,m,b,f,frame,fees,_store,_risk=setup
    x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],size=10),fees)
    t=x.state['exit_tournament'];baseline=copy.deepcopy(t)
    assert len({sum(p['cost'] for p in arm['positions'].values()) for arm in t['arms'].values()})==1
    with pytest.raises(ValueError):tournament.settle(t,{'verified':True},clock[0])
    assert t==baseline
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],bid=.32,ask=.34,size=10),fees)
    t=x.state['exit_tournament']
    assert t['arms']['risk_20pct']['closed']
    assert not t['arms']['hold_native']['closed']
    with pytest.raises(ValueError):
        corrupt=copy.deepcopy(t);corrupt['policy_sha256']='bad';tournament.advance(corrupt,[],{},clock[0])
    proof={'forecast_id':f['id'],'event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,'rules_sha256':f['rules_sha256'],
        'payout':1,'resolved_at':(clock[0]+timedelta(seconds=1)).isoformat(),'available_at':(clock[0]+timedelta(seconds=1)).isoformat(),
        'verified':True,'native_payout_verified':True}
    clock[0]+=timedelta(seconds=2);x.settle({f['id']:proof})
    assert x.state['exit_tournament']['arms']['hold_native']['closed']
    assert x.report()['exit_tournament']['arms']['hold_native']['verified_settlement_pnl']>0


def test_loss_attribution_reconciles_original_modeled_cash_identity(setup):
    x,clock,_m,b,_f,frame,fees,_store,_risk=setup
    recorded=[];x.step(frame,fees);recorded+=events(x)
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees);recorded+=events(x)
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],bid=.74,ask=.76),fees);recorded+=events(x)
    report=economics.attribution(economics.ledger(recorded))
    assert report['unmatched_exits']==0
    for t in report['trades']:
        assert t['gross_price_pnl']-t['allocated_entry_fees']-t['exit_fees']-t['entry_reserve']-t['exit_slippage']==pytest.approx(t['modeled_exit_pnl'])
        assert t['probability_error'] is None
    assert digest(x.state['loss_ledger'])==digest(economics.ledger(recorded))


def test_tournament_never_marks_old_or_unavailable_books_as_current_profit(setup):
    x,clock,_m,b,_f,frame,fees,_store,_risk=setup
    x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees)
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees)
    clock[0]+=timedelta(seconds=20)
    assert x.report()['exit_tournament']['arms']['hold_native']['unrealized_net_pnl'] is None


def test_matched_arms_refuse_excess_exposure_and_no_double_counted_bid_marks(setup):
    x,clock,m,b,_f,frame,fees,_store,_risk=setup
    x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees)
    fills=[e for e in events(x) if e['type']=='modeled_fill' and e['profile']=='balanced']
    e=copy.deepcopy(fills[0]);t=tournament.initialize()
    e['cost']=26.
    tournament.advance(t,[e],{m.token_id:b},clock[0],markets={m.token_id:m})
    assert t['withholding_reasons']['matched_all_arm_risk_budget']==1 and not t['entries']
    # Two lots must consume a single profile's available bid allocation when marked.
    e=copy.deepcopy(fills[0]);e['quantity']=8.;e['cost']=3.
    tournament.advance(t,[e],{m.token_id:b},clock[0],markets={m.token_id:m})
    e2=copy.deepcopy(e);e2['order_id']='CONTROLLED-other'
    tournament.advance(t,[e2],{m.token_id:b},clock[0],markets={m.token_id:m})
    arm=t['arms']['hold_native']
    marks=[p['last_mark'] for p in arm['positions'].values()]
    assert sum(mark['executable_quantity'] for mark in marks)<=10.+1e-8
    assert sum(mark['net_pnl'] is None for mark in marks)==1


def test_partial_fill_then_partial_exit_attribution_uses_available_cost_basis(setup):
    x,_clock,_m,_b,_f,frame,fees,_store,_risk=setup
    x.step(frame,fees);intent=next(e for e in events(x) if e['type']=='shadow_intent' and e['profile']=='balanced')
    common={'profile':'balanced','order_id':intent['order_id']}
    fill={**common,'type':'modeled_fill','quantity':2.,'cost':1.02,'levels':[{'price':.5,'quantity':2.,'fee':.01}]}
    exit={**common,'type':'modeled_exit','cost':.51,'pnl':-.02,'levels':[{'price':.5,'quantity':1.,'fee':.005}]}
    later={**fill,'quantity':1.,'cost':.42,'levels':[{'price':.4,'quantity':1.,'fee':.01}]}
    t=economics.attribution(economics.ledger([intent,fill,exit,later]))['trades'][0]
    assert t['allocated_entry_principal']==pytest.approx(.5)
    assert t['allocated_entry_fees']==pytest.approx(.005)
    assert t['entry_reserve']==pytest.approx(.005)


def test_no_entry_when_known_round_trip_already_triggers_risk_exit(setup):
    x,clock,_m,b,_f,frame,fees,_store,_risk=setup
    x.step(frame_at(frame,b,clock[0],bid=.10,ask=.15),fees)
    s=x.state['profiles']['balanced']
    assert not s['orders']
    assert any('entry_liquidation_already_breaches_20pct_exit_rule' in reason for reason in s['rejects'])
