"""Controlled metadata fixtures; never counted as real prospective evidence."""
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase35 import discovery
from test_phase35_weather import NOW, book, market


def frame():
    return SharedMarketFrame(id='CONTROLLED-frame',timestamp=NOW,available_at=NOW,source='CONTROLLED',producer_health={'status':'ok'},markets=(),books=())


async def test_real_contract_filter_namespace_restore_and_stationday_dedup(tmp_path,monkeypatch):
    m=market();duplicate=m.model_copy(update={'market_id':'CONTROLLED-M2','event_id':'CONTROLLED-E2','token_id':'CONTROLLED-2'})
    calls=[]
    async def acquire(**kw):calls.append(1);return [m,duplicate,m.model_copy(update={'token_id':'bad','question':'Wrong question?'})]
    monkeypatch.setattr(discovery.weather,'discover',acquire);store=EventStore(tmp_path/'controlled.sqlite')
    try:
        u=discovery.WorldWeatherUniverse(store,clock=lambda:NOW,can_write=lambda:True);f=await u.frame(frame())
        assert len(f.markets)==2 and len(f.books)==0 and u.status()['canonical_station_days']==1 and u.status()['native_parents']==2
        row=store.latest('WorldWeatherDiscoveryStudy',1)[0]
        assert row['source_frame_id']==frame().id and row['source_frame_sha256']==discovery.digest(frame().model_dump(mode='json'))
        restored=discovery.WorldWeatherUniverse(store,clock=lambda:NOW,can_write=lambda:True)
        assert (await restored.frame(frame())).id==f.id and len(calls)==1
        assert store.count(kind='DomainResearchStudy')==0
    finally:store.close()


async def test_bounds_roundrobin_and_fresh_books_do_not_drop_other_native_parents(tmp_path,monkeypatch):
    original=market();values=[original.model_copy(update={'market_id':str(i),'token_id':str(i),'event_id':f'parent-{i%2}'}) for i in range(120)]
    async def acquire(**kw):return values
    monkeypatch.setattr(discovery.weather,'discover',acquire);store=EventStore(tmp_path/'controlled.sqlite');clock=[NOW]
    try:
        u=discovery.WorldWeatherUniverse(store,clock=lambda:clock[0],can_write=lambda:True)
        base=frame().model_copy(update={'books':(book(values[-1]),)})
        got=await u.frame(base);assert len(got.markets)==100 and {m.event_id for m in got.markets}=={'parent-0','parent-1'}
        assert values[-1].token_id in {m.token_id for m in got.markets}
        first=[m.token_id for m in got.markets];clock[0]+=timedelta(minutes=15)
        second=[m.token_id for m in (await u.frame(base)).markets];assert second!=first
        assert set(first)|set(second)=={m.token_id for m in values}
        assert store.count(kind='WorldWeatherDiscoveryStudy')==2
    finally:store.close()


async def test_backpressure_and_base_identity_conflicts_fail_closed(tmp_path,monkeypatch):
    m=market()
    async def acquire(**kw):return [m]
    monkeypatch.setattr(discovery.weather,'discover',acquire);store=EventStore(tmp_path/'controlled.sqlite');allowed=[False]
    try:
        u=discovery.WorldWeatherUniverse(store,clock=lambda:NOW,can_write=lambda:allowed[0]);assert await u.frame(frame())==frame();assert store.count(kind='WorldWeatherDiscoveryStudy')==0
        allowed[0]=True
        bad=frame().model_copy(update={'markets':(m.model_copy(update={'question':'wrong'}),)})
        with pytest.raises(ValueError,match='identity_conflict'):await u.frame(bad)
    finally:store.close()
