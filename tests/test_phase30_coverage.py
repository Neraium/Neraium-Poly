"""Controlled discovery/metadata fixtures; no real forecast or fill claims."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase25 import discovery
from neraium_poly.research.phase30.coverage import WEATHER_QUERIES, discover_weather
from test_phase24_integration import inputs
from test_phase24_weather_economics import NOW, market


async def test_targeted_weather_route_uses_existing_exact_source_rule_interpreter():
    m=market();calls=[]
    async def search(queries,*,clock):calls.append(queries);return [m,m.model_copy(update={'resolution_source':'https://unreviewed.example'})]
    result=await discover_weather(clock=lambda:NOW,search=search)
    assert result==[m] and calls==[WEATHER_QUERIES]
    assert len(WEATHER_QUERIES)==3 and result[0].timestamp==m.timestamp


async def test_current_parent_diversity_dedup_and_maximum_are_enforced():
    m=market();values=[m.model_copy(update={'id':str(i),'market_id':str(i),'token_id':str(i),'event_id':'parent-'+str(i%3)}) for i in range(100)]
    async def search(*a,**k):return values+[values[0]]
    result=await discover_weather(clock=lambda:NOW,search=search,maximum=6)
    assert len(result)==6 and len({m.event_id for m in result[:3]})==3
    assert len({m.token_id for m in result})==6
    with pytest.raises(ValueError,match='bounded_weather_discovery'):await discover_weather(clock=lambda:NOW,search=search,maximum=65)


async def test_future_or_closed_metadata_is_not_substituted_into_research():
    m=market()
    async def search(*a,**k):return [m.model_copy(update={'available_at':NOW+timedelta(seconds=1)}),m.model_copy(update={'status':'closed'})]
    assert not await discover_weather(clock=lambda:NOW,search=search)


async def test_conflicting_supported_token_contract_is_quarantined():
    m=market()
    async def search(*a,**k):return [m,m.model_copy(update={'min_order_size':2})]
    with pytest.raises(ValueError,match='ambiguous_public_weather_token_identity'):await discover_weather(clock=lambda:NOW,search=search)


async def test_universe_discovers_weather_without_missing_module_discover_method(tmp_path,monkeypatch):
    from neraium_poly.research.phase30 import coverage
    m,_b,_e,_f,frame=inputs();extra=m.model_copy(update={'token_id':'CONTROLLED-weather-token','market_id':'CONTROLLED-weather-market'})
    async def actual_route(**kwargs):return [extra]
    monkeypatch.setattr(coverage,'discover_weather',actual_route)
    monkeypatch.setattr(discovery,'modules',lambda:{'weather':SimpleNamespace()})
    store=EventStore(tmp_path/'controlled.sqlite')
    try:
        u=discovery.Universe(store,clock=lambda:frame.available_at,can_write=lambda:True)
        result=await u.frame(frame)
        assert len(result.markets)==2 and result.books==frame.books
        record=store.latest('ExpansionDiscoveryStudy',limit=1)[0]
        assert record['discovery_policy_sha256']==u.policy_sha
        assert record['trading_authority'] is False and not record['rejections']
        await u.frame(frame);assert store.count(kind='ExpansionDiscoveryStudy')==1
    finally:store.close()


async def test_universe_source_failure_never_creates_metadata(tmp_path,monkeypatch):
    from neraium_poly.research.phase30 import coverage
    _m,_b,_e,_f,frame=inputs()
    async def unavailable(**kwargs):raise TimeoutError('CONTROLLED provider timeout')
    monkeypatch.setattr(coverage,'discover_weather',unavailable)
    monkeypatch.setattr(discovery,'modules',lambda:{'weather':SimpleNamespace()})
    store=EventStore(tmp_path/'controlled.sqlite')
    try:
        u=discovery.Universe(store,clock=lambda:frame.available_at,can_write=lambda:True)
        result=await u.frame(frame)
        assert result==frame and 'TimeoutError' in u.rejections['weather']
    finally:store.close()
