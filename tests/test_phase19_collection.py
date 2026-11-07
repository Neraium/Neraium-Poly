"""Controlled priority/protection fixtures; no genuine forecasts or account changes."""

import json
import sqlite3
from datetime import timedelta

import pytest
from neraium_poly.data.operational import DiscoveryBatch
from neraium_poly.data.polymarket import normalize_book, normalize_market
from neraium_poly.research.phase19.collection import protected_markets, select_priority_pool
from test_phase19_discovery import NOW, book, native


def fixture():
    raw={**native(), 'eventId':'CONTROLLED parent'}
    other={**native('ethereum'),'eventId':'CONTROLLED other parent'}
    base=DiscoveryBatch(tuple(normalize_market(other,NOW)),2,False,(),0)
    records=normalize_market(raw,NOW)
    books=[normalize_book(book(m.token_id),m.market_id,m.token_id,NOW).model_dump(mode='json') for m in records]
    return raw,records,base,{'markets':[raw],'books':books}


def test_additive_priority_keeps_broad_base_and_caps_native_subscriptions():
    _raw,_records,base,d=fixture()
    selected,pool,reasons=select_priority_pool(base,{},d,now=NOW,limit=2,max_tokens=4)
    assert not reasons and len(pool)==1 and len(selected.markets)==4
    assert {m.token_id for m in base.markets}.issubset(m.token_id for m in selected.markets)
    _,pool,reasons=select_priority_pool(base,{},d,now=NOW,limit=2,max_tokens=2)
    assert not pool and reasons['subscription_budget_full']==1


def test_stale_or_wrong_market_books_never_grant_priority():
    _raw,_records,base,d=fixture()
    for b in d['books']:b['timestamp']=(NOW-timedelta(seconds=60)).isoformat()
    _,pool,reasons=select_priority_pool(base,{},d,now=NOW,limit=2,max_tokens=4)
    assert not pool and reasons['no_fresh_two_sided_preflight_book']==1
    for b in d['books']:b['timestamp']=NOW.isoformat();b['market_id']='CONTROLLED wrong market'
    assert not select_priority_pool(base,{},d,now=NOW,limit=2,max_tokens=4)[1]


@pytest.mark.parametrize('status,protected,retained',[
    ('verified_read_only',(),False),('verified_read_only',('bitcoin-CONTROLLED-market',),True),
    ('unavailable_retain_priorities',(),True)])
def test_expired_priority_is_retired_only_after_verified_no_capital(status,protected,retained):
    raw,records,base,_d=fixture();previous={raw['id']:[m.model_dump(mode='json') for m in records]}
    future=NOW+timedelta(days=2)
    _,pool,_=select_priority_pool(base,previous,{'markets':[],'books':[]},now=future,limit=2,max_tokens=4,
        protected=protected,protection_status=status)
    assert bool(pool)==retained


def test_readonly_capital_protection_includes_open_orders_reservations_and_positions(tmp_path):
    broker=sqlite3.connect(tmp_path/'broker.sqlite');broker.execute('CREATE TABLE orders(intent TEXT, report TEXT)')
    broker.execute('INSERT INTO orders VALUES(?,?)',(json.dumps({'market_id':'open-order'}),json.dumps({'status':'open'})));broker.commit();broker.close()
    risk=sqlite3.connect(tmp_path/'risk.sqlite');risk.execute('CREATE TABLE positions(market TEXT,quantity REAL)');risk.execute('INSERT INTO positions VALUES(?,1)',('position',))
    risk.execute('CREATE TABLE reservations(market TEXT,released INTEGER,remaining REAL)');risk.execute('INSERT INTO reservations VALUES(?,0,2)',('reservation',));risk.commit();risk.close()
    assert protected_markets(tmp_path)==({'open-order','position','reservation'},'verified_read_only')
    assert protected_markets(tmp_path/'MISSING')[1]=='unavailable_retain_priorities'


async def test_priority_runtime_archives_decision_and_native_inputs_before_collection(tmp_path,monkeypatch):
    from neraium_poly.ops.live import LivePaperRuntime
    from neraium_poly.research.phase19 import collection
    from test_live_operation import Clock, FakeAdapter, configuration
    raw,_records,_base,d=fixture()
    async def discover(**kwargs):
        return {**d,'provenance':[],'health_by_market':{},'rejections':{},'requests_used':0}
    monkeypatch.setattr(collection,'discover_forecast_markets',discover)
    clock=Clock(NOW);adapter=FakeAdapter(clock)
    r=LivePaperRuntime(configuration(tmp_path,forecast_discovery_enabled=True,websocket_enabled=False,
        forecast_protected_directory=tmp_path/'MISSING'),adapter=adapter,clock=clock)
    try:
        await r.discover()
        rows=r.events.latest('ForecastDiscoveryStudy',1)
        assert len(rows)==1 and rows[0]['selected_market_ids']==[raw['id']]
        assert rows[0]['resulting_markets']==3 and not rows[0]['trading_authority']
        assert len(r.markets)==4 and len(r.ledger.get('forecast_priority_pool'))==1
        assert r.state()['cash']==500 and not r.broker.history()
    finally:await r.close()


async def test_native_forecast_replay_validates_evidence_without_inventing_training_cutoff(tmp_path):
    from copy import deepcopy

    from neraium_poly.data import EventStore
    from neraium_poly.research.phase18.continuous import IndependentEventResearch
    from neraium_poly.research.phase19.qualification import replay_event_forecast
    from test_phase18_continuous import Clock, collect, frame
    store=EventStore(tmp_path/'controlled.sqlite');clock=Clock()
    try:
        research=IndependentEventResearch(store,clock=clock,collector=collect);await research.step(frame(clock))
        row=store.latest('EventProbabilityStudy',1)[0];r=replay_event_forecast(row)
        assert r['verified'] and r['model_training_cutoff'] is None
        changed=deepcopy(row);changed['model_result']['reference_price']+=1
        assert not replay_event_forecast(changed)['verified']
    finally:store.close()


def test_retirement_grace_covers_inflight_preexpiry_approvals():
    raw,records,base,_d=fixture();previous={raw['id']:[m.model_dump(mode='json') for m in records]}
    after=records[0].end_time+timedelta(seconds=30)
    _,pool,_=select_priority_pool(base,previous,{'markets':[],'books':[]},now=after,limit=2,max_tokens=4,protection_status='verified_read_only')
    assert raw['id'] in pool


@pytest.mark.parametrize('change', ['event','rule','token'])
def test_retained_priority_cannot_be_silently_rebound_by_new_provider_data(change):
    from copy import deepcopy

    from neraium_poly.research.phase19.collection import PriorityIdentityError
    raw,records,base,d=fixture();previous={raw['id']:[m.model_dump(mode='json') for m in records]}
    changed=deepcopy(d)
    if change=='event':changed['markets'][0]['eventId']='CONTROLLED changed event'
    if change=='rule':changed['markets'][0]['description']+='CONTROLLED changed rule'
    if change=='token':changed['markets'][0]['clobTokenIds']='["CONTROLLED changed yes","CONTROLLED changed no"]'
    with pytest.raises(PriorityIdentityError):select_priority_pool(base,previous,changed,now=NOW,limit=2,max_tokens=4)


def test_retained_priority_cannot_be_silently_rebound_by_broad_baseline():
    from neraium_poly.research.phase19.collection import PriorityIdentityError
    raw,records,_base,_d=fixture();previous={raw['id']:[m.model_dump(mode='json') for m in records]}
    changed=tuple(m.model_copy(update={'event_id':'CONTROLLED changed event'}) for m in records)
    base=DiscoveryBatch(changed,1,False,(),0)
    with pytest.raises(PriorityIdentityError):select_priority_pool(base,previous,{'markets':[],'books':[]},now=NOW,limit=2,max_tokens=4)
