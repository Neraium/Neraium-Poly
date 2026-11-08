"""Synthetic engineering archives; never authentic forecasts/results."""
import hashlib
import io
import zipfile
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase23.models import forecast_models, map_challenger_contract
from neraium_poly.research.phase31 import crypto
from test_phase18_continuous import Clock, frame
from test_phase18_forecasting import CUTOFF, artifact, market

ASOF=datetime(2026,11,8,12,tzinfo=UTC)


def approve(_authorization,*,as_of):return {'authorized':True,'scope':'CONTROLLED fixture only'}


async def verify(forecast,**kwargs):
    return await crypto.verify_crypto_event(forecast,**kwargs,access_authorization={
        'purpose':'noncommercial_nonproduction_research','available_at':CUTOFF.isoformat(),'evidence_sha256':'0'*64},access_verifier=approve)


def replay(result,study,forecast,**kwargs):return crypto.replay_crypto_event(result,study,forecast,**kwargs,access_verifier=approve)


def archive(day,*,hit=None,rows=1440,micro=True):
    begin=int(datetime.combine(day,datetime.min.time(),UTC).timestamp())*(1000000 if micro else 1000);step=60000000 if micro else 60000
    values=[]
    for i in range(rows):
        low=74000 if hit is not None and i==hit else 74900
        values.append(f'{begin+i*step},74950,75000,{low},74970,2,{begin+(i+1)*step-1},1,2,1,1,0')
    name=f'BTCUSDT-1m-{day.isoformat()}.csv';stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:z.writestr(name,'\n'.join(values)+'\n')
    raw=stream.getvalue();check=(hashlib.sha256(raw).hexdigest()+'  '+name[:-4]+'.zip\n').encode();return raw,check


def original(cutoff=CUTOFF):
    m=market(now=cutoff);e=artifact(cutoff);c=map_challenger_contract(m,now=cutoff);f=forecast_models(c,(e,),cutoff=cutoff)[0];clock=Clock();clock.now=cutoff;book=frame(clock)['books'][0]
    f.update(id='CONTROLLED-original-forecast',timestamp=cutoff.isoformat(),market=m.model_dump(mode='json'),contract=c.model_dump(mode='json'),book=book,book_id=book['id'],book_sha256=digest(book),market_probability=.405)
    study={'id':'CONTROLLED-original-study','operation':'forecast_batch','timestamp':cutoff.isoformat(),'available_at':(cutoff+timedelta(seconds=1)).isoformat(),'forecasts':[f],'evidence':[e.model_dump(mode='json')],'trading_authority':False,'certification_authority':False}
    return study,f


@pytest.fixture(autouse=True)
def controlled(monkeypatch):
    crypto._CACHE.clear();monkeypatch.setattr(crypto.shutil,'disk_usage',lambda _p:SimpleNamespace(free=200*1024**3))


def install(monkeypatch,*,hit=None,missing=False):
    original_client=httpx.AsyncClient;calls=[]
    files={}
    for day in [date(2026,11,6),date(2026,11,7)]:
        raw,check=archive(day,hit=hit if day.day==7 else None);url=crypto.archive_url('BTCUSDT',day)
        files[url]=raw;files[url+'.CHECKSUM']=check
    def handle(request):
        url=str(request.url);calls.append(url)
        if missing and '2026-11-07' in url:return httpx.Response(404,text='CONTROLLED unpublished')
        return httpx.Response(200,content=files[url])
    monkeypatch.setattr(crypto.httpx,'AsyncClient',lambda **kw:original_client(transport=httpx.MockTransport(handle),**kw))
    return calls


def test_complete_microsecond_archive_and_legacy_ms_are_explicit():
    raw,check=archive(date(2026,11,6));r=crypto.parse_archive(raw,check,symbol='BTCUSDT',day=date(2026,11,6));assert len(r)==1440
    assert r[0]['open_us']==int(datetime(2026,11,6,tzinfo=UTC).timestamp())*1000000
    old=date(2024,1,1);raw,check=archive(old,micro=False);assert len(crypto.parse_archive(raw,check,symbol='BTCUSDT',day=old))==1440


@pytest.mark.parametrize('fault',['checksum','unit','incomplete','symbol'])
def test_bad_archive_checksum_unit_completeness_identity_fail_closed(fault):
    day=date(2026,11,6);raw,check=archive(day,micro=fault!='unit',rows=1439 if fault=='incomplete' else 1440)
    if fault=='checksum':check=b'0'*64+b'  BTCUSDT-1m-2026-11-06.zip\n'
    with pytest.raises(ValueError):crypto.parse_archive(raw,check,symbol='ETHUSDT' if fault=='symbol' else 'BTCUSDT',day=day)


@pytest.mark.parametrize('hit,outcome',[(None,0),(4*60,1)])
async def test_complete_exact_event_uses_original_model_and_market_baseline(monkeypatch,tmp_path,hit,outcome):
    s,f=original();calls=install(monkeypatch,hit=hit)
    result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    assert result['event_result_verified'] and result['official_result']['outcome']==outcome
    proof=replay(result,s,f,evidence_root=tmp_path,as_of=ASOF)
    assert proof['brier']==pytest.approx((f['probability']-outcome)**2)
    assert proof['market_brier']==pytest.approx((.405-outcome)**2)
    assert not proof['native_payout_verified'] and not proof['trading_authority'] and not proof['certification_authority']
    assert len(calls)==4 and result['official_result']['observed_event_minutes']==1440


async def test_missing_next_day_archive_never_manufactures_no(monkeypatch,tmp_path):
    _s,f=original();install(monkeypatch,missing=True)
    result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    assert not result['event_result_verified'] and result['missing_archives'][0]['status']==404
    assert result['reason']=='official_next_day_archive_missing_complete_ET_window'


async def test_prior_barrier_hit_cannot_score_an_already_known_outcome(monkeypatch,tmp_path):
    _s,f=original();install(monkeypatch,hit=2*60)
    result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    assert not result['event_result_verified'] and result['reason']=='barrier_outcome_precedes_original_forecast'


@pytest.mark.parametrize('fault',['corrupt','foreign_rules','different_side','future_receipt','native_authority','late_publication','different_outcome','path_escape'])
async def test_replay_original_source_and_authority_checks(monkeypatch,tmp_path,fault):
    s,f=original();install(monkeypatch,hit=4*60);result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    if fault=='corrupt':
        ref=result['official_evidence'][0]['archive'];(tmp_path/result['evidence_directory']/ref['raw_file']).write_bytes(b'CONTROLLED CORRUPT')
    elif fault=='foreign_rules':result['rules_sha256']='f'*64
    elif fault=='different_side':f=deepcopy(f);f['contract']['parameters']['selected_outcome']='No'
    elif fault=='future_receipt':result['official_evidence'][0]['archive']['retrieved_at']=(ASOF+timedelta(seconds=1)).isoformat()
    elif fault=='native_authority':result['native_payout_verified']=True
    elif fault=='late_publication':s={**s,'available_at':ASOF.isoformat()}
    elif fault=='different_outcome':result['official_result']['outcome']=0
    else:result['official_evidence'][0]['archive']['raw_file']='../foreign'
    with pytest.raises((ValueError,KeyError)):replay(result,s,f,evidence_root=tmp_path,as_of=ASOF)


async def test_restricted_access_is_not_retried_through_another_host(monkeypatch,tmp_path):
    _s,f=original();real=httpx.AsyncClient;calls=[]
    def handle(request):calls.append(str(request.url));return httpx.Response(451,text='CONTROLLED restricted')
    monkeypatch.setattr(crypto.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    assert not result['event_result_verified'] and len(calls)==1 and calls[0].startswith(crypto.ORIGIN)


async def test_storage_floor_prevents_any_network_download(monkeypatch,tmp_path):
    _s,f=original();monkeypatch.setattr(crypto.shutil,'disk_usage',lambda _p:SimpleNamespace(free=99*1024**3));calls=install(monkeypatch)
    result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    assert not result['event_result_verified'] and 'filesystem_reserve' in result['reason'] and not calls


async def test_prospective_yes_can_be_verified_from_complete_prefix_archive(monkeypatch,tmp_path):
    cutoff=datetime(2026,11,6,22,tzinfo=UTC);s,f=original(cutoff)
    real=httpx.AsyncClient;day=date(2026,11,6);raw,check=archive(day,hit=23*60);url=crypto.archive_url('BTCUSDT',day)
    def handle(request):
        u=str(request.url)
        if u==url:return httpx.Response(200,content=raw)
        if u==url+'.CHECKSUM':return httpx.Response(200,content=check)
        return httpx.Response(404,text='CONTROLLED unpublished next day')
    monkeypatch.setattr(crypto.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    result=await verify(f,directory=tmp_path,clock=lambda:ASOF)
    assert result['event_result_verified'] and not result['official_result']['complete_event_window']
    proof=replay(result,s,f,evidence_root=tmp_path,as_of=ASOF)
    assert proof['outcome']==1 and datetime.fromisoformat(proof['event_end_lower'])<datetime.fromisoformat(f['event_end_time'])
    assert not proof['native_payout_verified']


async def test_license_default_closed_before_any_network_or_directory(monkeypatch,tmp_path):
    _s,f=original();calls=install(monkeypatch)
    result=await crypto.verify_crypto_event(f,directory=tmp_path/'not-created',clock=lambda:ASOF)
    assert not result['event_result_verified'] and 'eligible_use_authorization_required' in result['reason']
    assert not calls and not (tmp_path/'not-created').exists()
