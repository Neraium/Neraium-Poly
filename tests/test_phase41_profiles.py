"""Controlled prospective-engine tests, never authentic trading performance."""
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from neraium_poly.contracts import PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.research.phase41.simulation import ProfileExperiment
from test_phase24_integration import NOW, inputs


@pytest.fixture
def setup(tmp_path):
    m,b,_e,f,frame=inputs();f.update(id='CONTROLLED-forecast',market=m.model_dump(mode='json'),book=b.model_dump(mode='json'),calibration_status='unvalidated_research')
    clock=[NOW];store=EventStore(tmp_path/'profiles.sqlite')
    risk=json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits']
    engine=ProfileExperiment(store,clock=lambda:clock[0],risk_limits=risk,can_write=lambda:True)
    engine.enroll([f],verifier=lambda _:None)  # CONTROLLED fixture only; real driver replays native source/model.
    fees={m.token_id:{'status':'verified_current_protocol_curve','token_id':m.token_id,'as_of':NOW.isoformat(),'rate':.02}}
    yield engine,clock,f,m,b,frame,fees,store,risk
    store.close()


def tick(frame,b,now,*,size=None):
    changes={'id':'CONTROLLED-book-'+now.isoformat(),'timestamp':now,'available_at':now}
    if size is not None:changes['asks']=(PriceLevel(price=.46,size=size),)
    book=b.model_copy(update=changes)
    return frame.model_copy(update={'id':'CONTROLLED-frame-'+now.isoformat(),'timestamp':now,'available_at':now,'books':(book,)})


def test_aggressive_and_balanced_admit_uncalibrated_inputs_without_claiming_profit(setup):
    x,_clock,_f,_m,_b,frame,fees,_store,_risk=setup;x.step(frame,fees)
    r=x.report();assert r['profiles']['aggressive']['orders']==r['profiles']['balanced']['orders']==1
    assert r['profiles']['conservative']['orders']==0
    assert all(p['fill_events']==0 and p['open_positions']==0 and p['realized_simulated_pnl'] is None for p in r['profiles'].values())
    assert r['promotion']['research_recommendation'] is None
    assert not r['trading_authority'] and not r['actual_account_access']


def test_later_native_snapshot_partial_fills_and_measured_growth_only(setup):
    x,clock,_f,_m,b,frame,fees,_store,_risk=setup;x.step(frame,fees)
    clock[0]=NOW+timedelta(seconds=1)
    # A newer receipt/frame alone is not a subsequent exchange book.
    same=frame.model_copy(update={'timestamp':clock[0],'available_at':clock[0]});x.step(same,fees)
    assert x.report()['profiles']['aggressive']['fill_events']==0
    x.step(tick(frame,b,clock[0],size=40),fees)
    s=x.state['profiles']['aggressive'];p=next(iter(s['positions'].values()));assert p['quantity']==pytest.approx(4.)
    assert s['orders'] and s['cash']<500 and x.report()['profiles']['aggressive']['realized_simulated_pnl'] is None
    clock[0]+=timedelta(seconds=1);x.step(tick(frame,b,clock[0],size=40),fees)
    assert next(iter(x.state['profiles']['aggressive']['positions'].values()))['quantity']==pytest.approx(4.)
    clock[0]+=timedelta(seconds=1);x.step(tick(frame,b,clock[0],size=60),fees)
    assert next(iter(x.state['profiles']['aggressive']['positions'].values()))['quantity']==pytest.approx(6.)


def test_recovery_preserves_cash_positions_and_profile_identity(setup):
    x,clock,_f,_m,b,frame,fees,store,risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1);latest=tick(frame,b,clock[0]);x.step(latest,fees)
    before=copy.deepcopy(x.state);recovered=ProfileExperiment(store,clock=lambda:clock[0],risk_limits=risk,can_write=lambda:True)
    assert recovered.state==before
    recovered.step(latest,fees)
    assert recovered.state['profiles']['aggressive']['cash']==before['profiles']['aggressive']['cash']
    assert recovered.state['profiles']['aggressive']['fills']==before['profiles']['aggressive']['fills']


def test_missing_future_mismatched_or_expired_books_never_fill(setup):
    x,clock,_f,m,b,frame,fees,_store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1)
    future=tick(frame,b,clock[0]+timedelta(seconds=5)).model_copy(update={'timestamp':clock[0],'available_at':clock[0]})
    x.step(future,fees);assert x.report()['profiles']['aggressive']['fill_events']==0
    bad=tick(frame,b,clock[0]);bad=bad.model_copy(update={'markets':(m.model_copy(update={'question':'UNRELATED controlled event'}),)})
    x.step(bad,fees);assert x.report()['profiles']['aggressive']['fill_events']==0
    clock[0]+=timedelta(seconds=31);x.step(tick(frame,b,clock[0]),fees)
    assert x.report()['profiles']['aggressive']['fill_events']==0 and x.state['profiles']['aggressive']['expired']==1


def test_exposure_limits_and_native_payout_required_for_realized_shadow_pnl(setup):
    x,clock,f,m,b,frame,fees,_store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(tick(frame,b,clock[0]),fees)
    for s in x.state['profiles'].values():assert x.exposure(s)<=100+1e-9 and x.exposure(s,'market_id',m.market_id)<=25+1e-9
    clock[0]+=timedelta(seconds=2)
    proof={'verified':True,'forecast_id':f['id'],'market_id':m.market_id,'token_id':m.token_id,'event_id':m.event_id,'rules_sha256':f['rules_sha256'],
        'payout':1.,'resolved_at':(NOW+timedelta(seconds=2)).isoformat(),'available_at':clock[0].isoformat()}
    with pytest.raises(ValueError,match='native verified'):x.settle(lambda *_:proof)
    assert x.report()['profiles']['aggressive']['realized_simulated_pnl'] is None
    assert x.settle(lambda *_:{**proof,'native_payout_verified':True})
    r=x.report()['profiles']['aggressive'];assert r['settled_positions']==1 and r['open_positions']==0 and r['unrealized_simulated_pnl']==0
    assert r['marked_equity']==pytest.approx(500+r['realized_simulated_pnl'])
    assert not x.settle(lambda *_:{**proof,'native_payout_verified':True})


def test_storage_failure_never_adopts_an_uncommitted_fill(setup):
    x,clock,_f,_m,b,frame,fees,_store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1);before=copy.deepcopy(x.state)
    x.can_write=lambda:False
    with pytest.raises(ValueError,match='storage backpressure'):x.step(tick(frame,b,clock[0]),fees)
    assert x.state==before


def test_risk_increase_and_backdated_enrollment_reject(setup):
    x,clock,f,_m,_b,_frame,_fees,store,risk=setup
    with pytest.raises(ValueError,match='risk ceilings'):
        ProfileExperiment(store,clock=lambda:clock[0],risk_limits={**risk,'market_fraction':.5},can_write=lambda:True)
    old={**f,'id':'CONTROLLED-backdated','timestamp':(NOW-timedelta(seconds=1)).isoformat()}
    with pytest.raises(ValueError,match='prospective'):x.enroll([old],verifier=lambda _:None)


def test_drawdown_suspension_does_not_reset_on_next_day(setup):
    x,clock,_f,_m,b,frame,fees,_store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1);x.step(tick(frame,b,clock[0]),fees)
    # Controlled prior peak, representing earlier hypothetical performance.
    x.state['profiles']['aggressive']['peak_equity']=550.
    clock[0]+=timedelta(seconds=1);x.step(tick(frame,b,clock[0]),fees)
    assert x.state['profiles']['aggressive']['suspended']
    clock[0]+=timedelta(days=1);x.step(tick(frame,b,clock[0]),fees)
    assert x.state['profiles']['aggressive']['suspended']


def test_lost_append_acknowledgement_recovers_without_duplicate_fills(setup,monkeypatch):
    x,clock,_f,_m,b,frame,fees,store,_risk=setup;x.step(frame,fees);clock[0]+=timedelta(seconds=1)
    append=store.append
    def lost(record):append(record);raise OSError('CONTROLLED lost acknowledgement')
    monkeypatch.setattr(store,'append',lost)
    with pytest.raises(OSError):x.step(tick(frame,b,clock[0]),fees)
    assert x.state['profiles']['aggressive']['fills']==0
    monkeypatch.setattr(store,'append',append);clock[0]+=timedelta(seconds=1)
    assert x.step(tick(frame,b,clock[0]),fees) is False
    assert x.state['profiles']['aggressive']['fills']==1
    cash=x.state['profiles']['aggressive']['cash'];x.step(tick(frame,b,clock[0]),fees)
    assert x.state['profiles']['aggressive']['cash']==cash


async def test_repeated_cycles_resume_same_portfolio_instead_of_resetting_capital(monkeypatch,tmp_path):
    from neraium_poly.research.phase41 import experiment
    calls=[]
    async def cycle(output,**kwargs):calls.append((output,kwargs));return {'cycle':len(calls)}
    monkeypatch.setattr(experiment,'run',cycle)
    assert await experiment.repeat(tmp_path,cycles=3,seconds=10)=={'cycle':3}
    assert [v[1]['resume'] for v in calls]==[False,True,True]
    assert all(v[0]==tmp_path for v in calls)


def test_positive_sub_three_cent_research_edge_is_eligible(setup):
    x,_clock,f,_m,_b,frame,fees,_store,_risk=setup
    small={**f,'id':'CONTROLLED-small-edge','probability':.48}
    x.enroll([small],verifier=lambda _:None)
    x.step(frame,fees)
    for name in ('aggressive','balanced'):
        orders=[o for o in x.state['profiles'][name]['orders'].values() if o['forecast_id']==small['id']]
        assert len(orders)==1
        assert .48-(.46+.02*.46*.54+.002)<.03
    assert not x.state['profiles']['conservative']['orders']


async def test_native_bridge_never_requests_future_outcomes(setup,monkeypatch,tmp_path):
    from neraium_poly.research.phase41 import native
    _x,clock,f,_m,_b,_frame,_fees,store,_risk=setup
    async def forbidden(*args,**kwargs):raise AssertionError('future outcome requested')
    monkeypatch.setattr(native,'acquire_verified_outcome',forbidden)
    bound={f['id']:{'forecast':f,'study':{'id':'CONTROLLED-study'}}}
    assert await native.collect(bound,store,tmp_path/'native',clock=lambda:clock[0],can_write=lambda:True)=={}
    assert store.latest('ProfilePayoutStudy',10)==[]


async def test_native_bridge_withholds_proofs_failing_independent_replay(setup,monkeypatch,tmp_path):
    from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
    from neraium_poly.research.phase41 import native
    _x,clock,f,_m,_b,_frame,_fees,store,_risk=setup
    clock[0]=native.at(f['event_end_time'])+timedelta(seconds=1)
    outcome=VerifiedEventOutcome(id='CONTROLLED-invalid-proof',timestamp=clock[0],available_at=clock[0],source='CONTROLLED',
        event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],payout=1,
        resolution_rules_sha256=f['rules_sha256'],settled_at=clock[0],verification_source='CONTROLLED',proof_sha256='0'*64,verification={})
    async def invalid(*args,**kwargs):return outcome
    monkeypatch.setattr(native,'acquire_verified_outcome',invalid)
    monkeypatch.setattr(native,'verify_collected_outcome',lambda *args:False)
    bound={f['id']:{'forecast':f,'study':{'id':'CONTROLLED-study'}}}
    assert await native.collect(bound,store,tmp_path/'native',clock=lambda:clock[0],can_write=lambda:True)=={}
    rows=store.latest('ProfilePayoutStudy',10)
    assert len(rows)==1 and not rows[0]['verified'] and not rows[0]['trading_authority']
    assert await native.collect(bound,store,tmp_path/'native',clock=lambda:clock[0],can_write=lambda:False,max_requests=0)=={}
