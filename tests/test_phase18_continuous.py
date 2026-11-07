"""Controlled append-only event pipeline tests, never authentic forecast performance."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.research.phase18.continuous import IndependentEventResearch
from test_phase18_forecasting import CUTOFF, artifact, market


class Clock:
    def __init__(self):self.now=CUTOFF
    def __call__(self):return self.now


def frame(clock):
    m=market(now=clock());b=OrderBookSnapshot(id='controlled-event-book',timestamp=clock(),available_at=clock(),
        source='https://clob.polymarket.com',market_id=m.market_id,token_id=m.token_id,
        bids=(PriceLevel(price=.4,size=100),),asks=(PriceLevel(price=.41,size=100),))
    return {'id':'controlled-frame','available_at':clock().isoformat(),'producer_health':{'status':'ok'},
        'markets':[m.model_dump(mode='json')],'books':[b.model_dump(mode='json')]}


async def collect(_contract,*,now):return (artifact(now),)


async def test_prospective_forecast_and_two_rejected_policies_persist_restart(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    try:
        research=IndependentEventResearch(store,clock=clock,collector=collect)
        assert await research.step(frame(clock))
        r=research.summary();assert r['independent_research_forecasts']==1
        assert r['unreviewed_parent_events']==1 and r['pending_forecasts']==1
        assert r['qualified_training_events']==r['qualified_heldout_events']==0
        assert r['forecasts_by_domain']=={'crypto':1} and not r['trading_authority']
        row=store.latest('EventProbabilityStudy',1)[0]
        assert row['forecast']['timestamp']<=row['available_at'] and row['evidence']
        assert row['forecast']['uncertainty']['upper_probability']==1
        assert row['forecast']['calibration_status']=='unvalidated_research'
        assert all(p['rejected']==1 and p['orders']==0 and p['net_pnl'] is None for p in r['approaches'].values())
        recovered=IndependentEventResearch(store,clock=clock,collector=collect)
        assert recovered.state==research.state and not await recovered.step(frame(clock))
        assert store.count()==1
    finally:store.close()


async def test_source_failure_and_stale_quote_withhold_forecast_not_fabricate(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    async def fail(*_a,**_k):raise OSError('CONTROLLED unavailable provider')
    try:
        r=IndependentEventResearch(store,clock=clock,collector=fail)
        assert await r.step(frame(clock))
        assert r.summary()['independent_research_forecasts']==0
        assert store.latest('EventProbabilityStudy',1)[0]['forecast'] is None
        clock.now+=timedelta(minutes=6)
        r=IndependentEventResearch(store,clock=clock,collector=collect)
        old=frame(clock);old['available_at']=(clock()-timedelta(minutes=1)).isoformat()
        assert not await r.step(old) and r.last_error=='fresh_qualified_shared_market_frame_required'
    finally:store.close()


async def test_ambiguous_commit_recovers_once_without_duplicate_forecasts(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    try:
        r=IndependentEventResearch(store,clock=clock,collector=collect);before=deepcopy(r.state);append=store.append
        def lost(row):append(row);raise OSError('CONTROLLED lost acknowledgement')
        monkeypatch.setattr(store,'append',lost)
        with pytest.raises(OSError):await r.step(frame(clock))
        assert r.state==before and store.count()==1
        monkeypatch.setattr(store,'append',append)
        assert not await r.step(frame(clock))
        assert r.summary()['independent_research_forecasts']==1 and store.count()==1
    finally:store.close()


async def test_storage_backpressure_never_requests_external_data(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock();calls=[]
    async def collector(*a,**kw):calls.append(1);return await collect(*a,**kw)
    try:
        r=IndependentEventResearch(store,clock=clock,collector=collector,can_write=lambda:False)
        assert not await r.step(frame(clock)) and not calls and store.count()==0
        assert r.last_error=='event_research_storage_backpressure'
    finally:store.close()


async def test_corrupted_checkpoint_does_not_reset_research(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    try:
        r=IndependentEventResearch(store,clock=clock,collector=collect);await r.step(frame(clock))
        row=deepcopy(store.latest('EventProbabilityStudy',1)[0]);row['checkpoint_sha256']='0'*64
        monkeypatch.setattr(store,'latest',lambda *_a,**_k:[row])
        with pytest.raises(ValueError,match='integrity'):IndependentEventResearch(store,clock=clock)
    finally:store.close()


async def test_incomplete_commit_checkpoint_rolls_back_volatile_forecast(tmp_path,monkeypatch):
    import neraium_poly.research.phase18.continuous as module
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    try:
        r=IndependentEventResearch(store,clock=clock,collector=collect);before=deepcopy(r.state)
        monkeypatch.setattr(module,'pack_checkpoint',lambda _state:(_ for _ in ()).throw(ValueError('CONTROLLED codec bound')))
        with pytest.raises(ValueError):await r.step(frame(clock))
        assert r.state==before and store.count()==0
    finally:store.close()


async def test_unknown_settlement_proof_preserves_pending_without_price_inference(tmp_path,monkeypatch):
    import neraium_poly.research.phase12.outcome_collector as module
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    async def unavailable(*_a,**_kw):return None
    monkeypatch.setattr(module,'acquire_verified_outcome',unavailable)
    try:
        r=IndependentEventResearch(store,clock=clock,collector=collect);await r.step(frame(clock))
        clock.now+=timedelta(hours=3)
        assert await r.resolve_pending(tmp_path/'proofs')
        assert r.summary()['durable_outcome_records']==0 and r.summary()['pending_forecasts']==1
        saved=store.latest('EventProbabilityStudy',1)[0]
        assert saved['outcome'] is None and saved['operation']=='outcome_check'
        assert saved['model_result']['reasons']==['native_finalized_settlement_proof_unavailable']
    finally:store.close()
