"""Controlled future reference results only; no live evidence is fabricated."""
import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase35 import outcomes, weather
from neraium_poly.research.phase35.continuous import WorldWeatherResearch
from test_phase35_weather import NOW, book, evidence, market

OBSERVED=datetime.fromisoformat('2026-11-10T20:00:00+00:00')


@pytest.fixture(autouse=True)
def available_disk(monkeypatch):
    monkeypatch.setattr(outcomes.shutil,'disk_usage',lambda _:SimpleNamespace(free=200*1024**3))


async def original(monkeypatch):
    async def collect(*a,**kw):return evidence()
    monkeypatch.setattr(weather,'collect',collect);m=market();r=await weather.forecast(m,book(m),clock=lambda:NOW)
    f=r['forecasts'][0];f['id']='CONTROLLED-original-forecast'
    return f,{'id':'CONTROLLED-study','available_at':NOW.isoformat(),'forecasts':[f],'evidence':r['evidence']}


def install_source(monkeypatch,c):
    async def fetch(client,url,clock):
        start=datetime.fromisoformat(c['period_start']);rows=[]
        for hour in range(28):
            t=start+timedelta(hours=hour);rows.append({'icaoId':c['station'],'obsTime':int(t.timestamp()),'receiptTime':(t+timedelta(minutes=5)).isoformat(),'rawOb':f"METAR {c['station']} {t:%d%H%M}Z 00000MPS 9999 SCT030 17/10 Q1020"})
        raw=json.dumps(rows).encode();return raw,{'source_url':url,'retrieved_at':outcomes.at(clock()).isoformat(),'content_sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    monkeypatch.setattr(outcomes,'_fetch',fetch)


async def test_new_exact_station_reference_replay_remains_conditional_not_native(monkeypatch,tmp_path):
    f,s=await original(monkeypatch);install_source(monkeypatch,f['contract']);r=await outcomes.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    assert r['event_result_verified'] and r['official_result']['resolution_value']==17
    score=outcomes.replay_weather_event(r,s,f,evidence_root=tmp_path,as_of=OBSERVED)
    assert score['outcome']==0 and score['brier']==f['probability']**2
    assert not score['market_baseline_comparable'] and score['market_brier'] is None and not score['native_payout_verified']
    assert not score['trading_authority'] and not score['certification_authority']


@pytest.mark.parametrize('fault',['raw','identity','original_probability','future_study','source_url'])
async def test_replay_rejects_corruption_identity_temporal_and_source_changes(fault,monkeypatch,tmp_path):
    f,s=await original(monkeypatch);install_source(monkeypatch,f['contract']);r=await outcomes.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    if fault=='raw':(tmp_path/r['evidence_directory']/r['official_evidence'][0]['raw_file']).write_text('[]')
    elif fault=='identity':r['token_id']='wrong'
    elif fault=='original_probability':f['probability']+=.01
    elif fault=='future_study':s['available_at']=f['contract']['period_start']
    elif fault=='source_url':r['official_evidence'][0]['source_url']='https://wrong.example'
    with pytest.raises(ValueError):outcomes.replay_weather_event(r,s,f,evidence_root=tmp_path,as_of=OBSERVED)


async def test_future_does_not_query_and_disk_reserve_fails_closed(monkeypatch,tmp_path):
    f,_=await original(monkeypatch)
    async def forbidden(*a,**kw):raise AssertionError('must not fetch')
    monkeypatch.setattr(outcomes,'_fetch',forbidden);directory=tmp_path/'future'
    r=await outcomes.verify_weather_event(f,directory=directory,clock=lambda:NOW);assert r['status']=='pending' and not directory.exists()
    monkeypatch.setattr(outcomes.shutil,'disk_usage',lambda _:SimpleNamespace(free=99*1024**3))
    r=await outcomes.verify_weather_event(f,directory=directory,clock=lambda:OBSERVED);assert not r['event_result_verified'] and 'filesystem_reserve' in r['reason']


async def test_scheduler_bounds_recovery_idempotence_and_independent_stationday(monkeypatch,tmp_path):
    from neraium_poly.experimental.contracts import SharedMarketFrame
    async def collect(*a,**kw):return evidence()
    monkeypatch.setattr(weather,'collect',collect);m=market();clock=[NOW];store=EventStore(tmp_path/'controlled.sqlite')
    try:
        controller=WorldWeatherResearch(store,clock=lambda:clock[0]);frame=SharedMarketFrame(id='CONTROLLED-frame',timestamp=NOW,available_at=NOW,source='CONTROLLED',producer_health={'status':'ok'},markets=(m,),books=(book(m),))
        assert await controller.step(frame);f=store.latest('WorldWeatherResearchStudy',1)[0]['forecasts'][0];install_source(monkeypatch,f['contract'])
        engine=outcomes.WorldWeatherOutcomes(store,tmp_path/'references',clock=lambda:clock[0]);assert not await engine.step() and engine.state['checks']==0
        clock[0]=OBSERVED;assert await engine.step() and engine.state['checks']==2
        assert len(engine.state['verified'])==2 and engine.status()['independent_event_count']==1
        assert not await engine.step() and engine.state['checks']==2
        restored=outcomes.WorldWeatherOutcomes(store,tmp_path/'references',clock=lambda:clock[0]);assert restored.state==engine.state
        clock[0]+=timedelta(seconds=301);assert not await restored.step() and restored.state['checks']==2
        assert store.count(kind='DomainOutcomeStudy')==0
        rows=store.latest('WorldWeatherOutcomeStudy',10);verified=[r for r in rows if r['operation']=='outcome_check']
        assert len(verified)==2 and all(r['original_kind']=='WorldWeatherResearchStudy' for r in verified)
        assert all(not r['result']['descriptive_score']['native_payout_verified'] for r in verified)
        for row in verified:
            study=outcomes._original(store,row['original_study_id']);forecast=next(f for f in study['forecasts'] if f['id']==row['forecast_id'])
            assert outcomes.replay_weather_event(row['result'],study,forecast,evidence_root=tmp_path/'references',as_of=clock[0])==row['result']['descriptive_score']
    finally:store.close()


async def test_source_head_gap_and_backpressure_fail_closed(tmp_path):
    class Store:
        def __init__(self):self.rows=[]
        def latest(self,kind,limit=100):return self.rows if kind=='WorldWeatherResearchStudy' else []
        def append(self,row):raise AssertionError('no append')
    store=Store();engine=outcomes.WorldWeatherOutcomes(store,tmp_path,clock=lambda:NOW,can_write=lambda:False)
    assert not await engine.step();engine.can_write=lambda:True
    engine.state['source_heads']['WorldWeatherResearchStudy']='missing'
    with pytest.raises(ValueError,match='source_head_gap'):await engine.step()
