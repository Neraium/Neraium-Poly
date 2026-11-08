"""Controlled weather engineering fixtures; never live outcome evidence."""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase24 import weather as model
from neraium_poly.research.phase32 import weather
from test_phase24_weather_economics import NOW, book, market, weather_evidence

OBSERVED=datetime(2026,11,8,20,tzinfo=UTC)


async def original(monkeypatch):
    async def collect(*a,**k):return weather_evidence()
    monkeypatch.setattr(model,'collect',collect)
    m=market();r=await model.forecast(m.model_dump(),book(m).model_dump(),clock=lambda:NOW)
    f=r['forecasts'][0];f['id']='CONTROLLED-weather-forecast'
    return f,{'forecasts':[f],'available_at':NOW.isoformat(),'evidence':r['evidence']}


def raw_rows(c):
    start=datetime.fromisoformat(c['period_start']);rows=[]
    for hour in range(28):
        t=start+timedelta(hours=hour)
        rows.append({'icaoId':c['station'],'obsTime':int(t.timestamp()),'receiptTime':(t+timedelta(minutes=5)).isoformat(),
            'rawOb':f"METAR {c['station']} {t:%d%H%M}Z 00000MPS 9999 SCT030 17/10 Q1020"})
    return rows


def install_source(monkeypatch,c,mutate=None):
    async def fetch(client,url,clock):
        rows=raw_rows(c)
        if mutate:mutate(rows)
        raw=json.dumps(rows).encode();return raw,{'source_url':url,'retrieved_at':OBSERVED.isoformat(),'content_sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    monkeypatch.setattr(weather,'_fetch',fetch)


async def test_official_station_result_separate_from_native_payout(monkeypatch,tmp_path):
    f,s=await original(monkeypatch);install_source(monkeypatch,f['contract'])
    r=await weather.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    assert r['event_result_verified'] and r['official_result']['resolution_value']==17
    p=weather.replay_weather_event(r,s,f,evidence_root=tmp_path,as_of=OBSERVED)
    assert p['outcome']==0 and p['brier']==f['probability']**2
    assert p['event_end_lower']=='2026-11-08T16:00:00+00:00'
    assert p['event_end_upper']=='2026-11-08T16:05:00+00:00'
    assert not p['native_payout_verified'] and not p['market_baseline_comparable'] and p['market_brier'] is None
    assert not p['trading_authority'] and not p['certification_authority']


async def test_future_event_does_not_request_or_create_files(monkeypatch,tmp_path):
    f,_=await original(monkeypatch)
    async def forbidden(*a,**k):raise AssertionError('future event must not query')
    monkeypatch.setattr(weather,'_fetch',forbidden)
    path=tmp_path/'not-created';r=await weather.verify_weather_event(f,directory=path,clock=lambda:NOW)
    assert not r['event_result_verified'] and r['status']=='pending' and not path.exists()


@pytest.mark.parametrize('fault',['missing_hour','no_following','wrong_station','raw_timestamp','conflicting_version','post_freeze_correction','truncated'])
async def test_incomplete_ambiguous_or_wrong_observations_withheld(fault,monkeypatch,tmp_path):
    f,_=await original(monkeypatch)
    def change(rows):
        if fault=='missing_hour':rows.pop(5)
        elif fault=='no_following':del rows[24:]
        elif fault=='wrong_station':rows[0]['icaoId']='ZUUU'
        elif fault=='raw_timestamp':rows[0]['rawOb']=rows[0]['rawOb'].replace('071600Z','071700Z')
        elif fault=='conflicting_version':rows.append({**rows[0],'rawOb':rows[0]['rawOb'].replace('17/10','18/10')})
        elif fault=='post_freeze_correction':rows[0]['receiptTime']='2026-11-08T18:00:00Z'
        elif fault=='truncated':rows[:]=[rows[0]]*400
    install_source(monkeypatch,f['contract'],change)
    r=await weather.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    assert not r['event_result_verified'] and not list(tmp_path.rglob('*.json'))


@pytest.mark.parametrize('fault',['raw_corrupt','rules','token','probability','future_publication','result','future_evidence'])
async def test_replay_binds_original_forecast_source_and_times(fault,monkeypatch,tmp_path):
    f,s=await original(monkeypatch);install_source(monkeypatch,f['contract'])
    r=await weather.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    if fault=='raw_corrupt':(tmp_path/r['evidence_directory']/r['official_evidence'][0]['raw_file']).write_text('[]')
    elif fault=='rules':f['rules_sha256']='0'*64
    elif fault=='token':r['token_id']='unrelated'
    elif fault=='probability':f['probability']=.9
    elif fault=='future_publication':s['available_at']=f['contract']['period_end']
    elif fault=='result':r['official_result']['resolution_value']=19
    elif fault=='future_evidence':r['official_evidence'][0]['retrieved_at']=(OBSERVED+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):weather.replay_weather_event(r,s,f,evidence_root=tmp_path,as_of=OBSERVED)


async def test_parent_group_is_station_day_not_contract_or_model(monkeypatch,tmp_path):
    f,_=await original(monkeypatch);install_source(monkeypatch,f['contract'])
    a=await weather.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    other=deepcopy(f);other['id']='CONTROLLED-second-model'
    b=await weather.verify_weather_event(other,directory=tmp_path,clock=lambda:OBSERVED)
    assert a['event_group_id']==b['event_group_id'] and a['forecast_id']!=b['forecast_id']
    assert len(list(tmp_path.rglob('*.json')))==1


def test_atomic_raw_publication_interruption_and_recovery(monkeypatch,tmp_path):
    raw=b'CONTROLLED';item={'source_url':'CONTROLLED'}
    def interrupt(*a):raise OSError('CONTROLLED interrupted publication')
    with monkeypatch.context() as patch:
        patch.setattr(weather.os,'link',interrupt)
        with pytest.raises(OSError):weather._save(tmp_path,raw,item)
    assert not list(tmp_path.iterdir())
    ref=weather._save(tmp_path,raw,item);assert (tmp_path/ref['raw_file']).read_bytes()==raw
    assert weather._save(tmp_path,raw,item)==ref
