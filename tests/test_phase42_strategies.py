"""Controlled strategy/execution tests; fixtures are NOT market evidence."""
import copy
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from neraium_poly.contracts import PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.ops.api import create_app
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase42.dashboard import snapshot
from neraium_poly.research.phase42.engine import StrategyEngine
from neraium_poly.research.phase42.strategies import DEFINITIONS, propose
from test_phase24_integration import NOW, inputs


@pytest.fixture
def setup(tmp_path):
    m,b,_e,f,frame=inputs();f.update(id='CONTROLLED',market=m.model_dump(mode='json'),book=b.model_dump(mode='json'),calibration_status='unvalidated',probability=.7,lower_probability=.55,market_probability=.455)
    risk=json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits'];store=EventStore(tmp_path/'research.sqlite');clock=[NOW]
    x=StrategyEngine(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    x.enroll([f],verifier=lambda _:None)
    fees={m.token_id:{'status':'verified_current_protocol_curve','token_id':m.token_id,'rate':.02,'as_of':NOW.isoformat(),'condition_id':'CONTROLLED-condition'}}
    yield x,clock,m,b,f,frame,fees,store,risk
    store.close()


def frame_at(frame,b,now,*,ask=.46,bid=.44,size=100):
    b=b.model_copy(update={'timestamp':now,'available_at':now,'id':'CONTROLLED-'+now.isoformat(),
        'asks':(PriceLevel(price=ask,size=size),),'bids':(PriceLevel(price=bid,size=size),)})
    return frame.model_copy(update={'timestamp':now,'available_at':now,'books':(b,)})


def events(x):return unpack_checkpoint(x.last['events'][0]['payload'])['decisions']


def test_small_shadow_entries_later_partial_depth_and_no_same_book_replenishment(setup):
    x,clock,_m,b,_f,frame,fees,_s,_risk=setup
    x.step(frame,fees);assert not x.state['profiles']['aggressive']['positions']
    clock[0]+=timedelta(seconds=1);sample=frame_at(frame,b,clock[0],size=10);x.step(sample,fees)
    s=x.state['profiles']['aggressive'];assert len(s['positions'])==1
    p=next(iter(s['positions'].values()));assert p['quantity']==pytest.approx(1.) and 'reserved' not in p
    assert sum(o.get('reserved',o.get('cost',0)) for o in [*s['orders'].values(),*s['positions'].values()] if o['strategy']=='independent')<=3.+1e-8
    cash=s['cash'];clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],size=10),fees)
    assert x.state['profiles']['aggressive']['cash']==cash


def test_bid_exit_is_realized_modeled_not_native_settlement_and_recovery_keeps_state(setup):
    x,clock,_m,b,_f,frame,fees,store,risk=setup;x.step(frame,fees)
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees)
    assert x.state['profiles']['balanced']['positions']
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],bid=.60,ask=.62),fees)
    closed=x.state['profiles']['balanced']['closed'];assert closed and closed[0]['pnl']>0 and not closed[0]['native_settled']
    assert any(e['type']=='modeled_exit' and e['book']['bids'][0]['price']==.60 for e in events(x))
    recovered=StrategyEngine(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True)
    assert recovered.state==x.state
    assert recovered.report()['profiles']['balanced']['strategies']['independent']['verified_settlement_net_pnl']==0


def test_passive_order_requires_later_crossed_limit_not_a_repeated_quote(setup):
    x,clock,_m,b,_f,frame,fees,_store,_risk=setup
    wide=frame_at(frame,b,NOW,bid=.40,ask=.46);x.step(wide,fees)
    orders=[o for o in x.state['profiles']['aggressive']['orders'].values() if o['strategy']=='spread_capture'];assert orders
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],bid=.40,ask=.46),fees)
    assert not any(p['strategy']=='spread_capture' for p in x.state['profiles']['aggressive']['positions'].values())
    clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0],bid=.38,ask=.40),fees)
    assert any(p['strategy']=='spread_capture' for p in x.state['profiles']['aggressive']['positions'].values())


def test_distinct_momentum_and_external_revision_hypotheses_are_causal(setup):
    _x,_clock,m,b,f,_frame,fees,_store,_risk=setup;now=NOW+timedelta(seconds=40)
    h={m.token_id:[{'at':(NOW+timedelta(seconds=i*10)).isoformat(),'mid':.40+i*.01} for i in range(4)]}
    old={**f,'id':'CONTROLLED-old','probability':.45,'timestamp':(NOW-timedelta(seconds=10)).isoformat(),'evidence_cutoff':(NOW-timedelta(seconds=11)).isoformat()}
    cs,_=propose({m.token_id:m},{m.token_id:b},{f['id']:f},h,{m.token_id:old},fees,now)
    found={c['strategy']:c for c in cs};assert len(DEFINITIONS)==5
    assert found['momentum']['probability'] is None
    assert found['event_repricing']['revision_from']['id']=='CONTROLLED-old'
    assert found['independent']['forecast']['id']==f['id']


def test_cross_market_identity_must_match_verified_binary_condition(setup):
    _x,_clock,m,b,_f,_frame,fees,_store,_risk=setup
    z=m.model_copy(update={'token_id':'CONTROLLED-NO','outcome':'No'});bz=b.model_copy(update={'token_id':z.token_id})
    fz={**fees[m.token_id],'token_id':z.token_id};fs={**fees,z.token_id:fz}
    cs,_=propose({m.token_id:m,z.token_id:z},{m.token_id:b,z.token_id:bz},{},{},{},fs,NOW)
    assert len([c for c in cs if c['strategy']=='consistency'])==2
    fs[z.token_id]={**fz,'condition_id':'UNRELATED'}
    cs,rs=propose({m.token_id:m,z.token_id:z},{m.token_id:b,z.token_id:bz},{},{},{},fs,NOW)
    assert not any(c['strategy']=='consistency' for c in cs)
    assert any('identity' in r['reason'] for r in rs)


def test_future_or_changed_identity_does_not_fill_and_storage_failure_is_atomic(setup):
    x,clock,m,b,_f,frame,fees,_store,_risk=setup;x.step(frame,fees);before=copy.deepcopy(x.state)
    with pytest.raises(ValueError):x.step(frame_at(frame,b,NOW+timedelta(seconds=1)),fees)
    assert x.state==before
    clock[0]+=timedelta(seconds=1)
    changed=frame_at(frame,b,clock[0]).model_copy(update={'markets':(m.model_copy(update={'resolution_rules':'UNRELATED'}),)})
    x.step(changed,fees);assert not x.state['profiles']['aggressive']['positions']
    before=copy.deepcopy(x.state);x.can_write=lambda:False
    with pytest.raises(ValueError):x.step(frame_at(frame,b,clock[0]),fees)
    assert x.state==before


def test_official_result_alone_cannot_settle_shadow_inventory(setup):
    x,clock,m,b,f,frame,fees,_store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(frame_at(frame,b,clock[0]),fees)
    proof={'forecast_id':f['id'],'event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,'rules_sha256':f['rules_sha256'],'payout':1,
        'resolved_at':(clock[0]+timedelta(seconds=1)).isoformat(),'available_at':(clock[0]+timedelta(seconds=1)).isoformat(),'verified':True}
    clock[0]+=timedelta(seconds=2)
    with pytest.raises(ValueError):x.settle({f['id']:proof})
    assert x.state['profiles']['aggressive']['positions']
    x.settle({f['id']:{**proof,'native_payout_verified':True}})
    assert not x.state['profiles']['aggressive']['positions'] and x.report()['verified_outcomes']==1
    assert x.settle({f['id']:{**proof,'native_payout_verified':True}}) is False


def test_dashboard_staleness_and_read_only_routes(setup):
    x,clock,_m,_b,_f,frame,fees,_store,_risk=setup;x.step(frame,fees)
    runtime=SimpleNamespace(shadow_research_snapshot=x.report(),shadow_research_error=None)
    assert snapshot(runtime,clock[0])['status']=='fresh'
    assert snapshot(runtime,clock[0]+timedelta(seconds=21))['status']=='stale'
    client=TestClient(create_app(runtime=runtime));assert client.get('/research').status_code==200
    assert client.get('/api/shadow-research').json()['trading_authority'] is False
    assert client.post('/api/shadow-research').status_code==405


async def test_opt_in_service_loop_uses_async_worker_and_never_account_access(monkeypatch,tmp_path):
    import asyncio

    from neraium_poly.research.phase42 import controller
    from neraium_poly.risk import RiskLimits
    monkeypatch.setenv('NERAIUM_SHADOW_RESEARCH','true')
    def forbidden(*args):raise AssertionError('actual account access')
    runtime=SimpleNamespace(stopping=False,last_frame='CONTROLLED-frame',events=None,config=SimpleNamespace(risk_limits=RiskLimits(),data_dir=tmp_path),
        clock=lambda:NOW,account=SimpleNamespace(place_order=forbidden))
    async def budget():return True
    async def io(factory):return await factory()
    runtime._async_budget_ok=budget;runtime._budget_ok=lambda:True;runtime._research_io=io
    class Controlled:
        def __init__(self,*args,**kwargs):pass
        def tick(self,frame,fees):
            with pytest.raises(RuntimeError):asyncio.get_running_loop()  # Synchronous IO is off the event loop.
            assert frame=='CONTROLLED-frame';runtime.stopping=True;return {'as_of':NOW.isoformat(),'trading_authority':False}
    monkeypatch.setattr(controller,'Controller',Controlled)
    await controller.service_loop(runtime,lambda:False)
    assert runtime.shadow_research_error is None and not runtime.shadow_research_snapshot['trading_authority']


def test_lost_ack_and_shared_exposure_limits(setup,monkeypatch):
    x,clock,_m,b,_f,frame,fees,store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1)
    append=store.append
    def lose(record):append(record);raise OSError('CONTROLLED lost ack')
    monkeypatch.setattr(store,'append',lose)
    with pytest.raises(OSError):x.step(frame_at(frame,b,clock[0]),fees)
    monkeypatch.setattr(store,'append',append)
    x.step(frame_at(frame,b,clock[0]),fees)
    for s in x.state['profiles'].values():
        assert s['cash']>=0 and x.exposure(s)<=100+1e-8
        for p in s['positions'].values():
            assert x.exposure(s,'market_id',p['market_id'])<=25+1e-8
            assert x.exposure(s,'event_id',p['event_id'])<=50+1e-8


def test_depth_retention_is_bounded_without_inventing_liquidity(setup):
    x,_clock,_m,b,_f,frame,fees,_store,_risk=setup
    asks=tuple(PriceLevel(price=.46+i*.01,size=100+i) for i in range(20));bids=tuple(PriceLevel(price=.44-i*.01,size=100+i) for i in range(20))
    book=b.model_copy(update={'asks':asks,'bids':bids});x.step(frame.model_copy(update={'books':(book,)}),fees)
    for s in x.state['profiles'].values():
        assert len(s['books'][b.token_id]['asks'])==8 and len(s['books'][b.token_id]['bids'])==8
    assert x.policy['depth_levels_per_side']==8


def test_controller_persists_original_source_bindings_for_restart_settlement(setup,monkeypatch,tmp_path):
    from neraium_poly.contracts import Record
    from neraium_poly.research.phase42 import controller
    _x,clock,_m,_b,f,frame,fees,store,risk=setup
    # Isolate actual archive mechanics from controlled model replay.
    class ControlledSource(Record):
        forecasts:list
    source=ControlledSource(id='CONTROLLED-original-study',timestamp=NOW,available_at=NOW,source='CONTROLLED',forecasts=[f])
    store.append(source);bound={f['id']:{'forecast':f,'study':source.model_dump(mode='json')}}
    monkeypatch.setattr(controller,'bound_forecasts',lambda *args,**kwargs:(bound,{}))
    monkeypatch.setattr(controller,'replay_model',lambda *args,**kwargs:None)
    c=controller.Controller(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True,directory=tmp_path/'native')
    c.tick(frame,fees);assert c.bindings[f['id']]['study_id']==source.id
    recovered=controller.Controller(store,risk_limits=risk,clock=lambda:clock[0],can_write=lambda:True,directory=tmp_path/'native')
    assert recovered.bindings==c.bindings
    assert recovered.engine.state==c.engine.state
    assert recovered.profiles.state==c.profiles.state
