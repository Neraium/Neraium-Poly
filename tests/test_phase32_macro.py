"""Controlled engineering sources only; not authentic macro outcomes."""
import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase32 import macro
from test_phase24_weather_economics import fomc_evidence
from test_phase24_weather_economics import market as fomc_market
from test_phase25_finance_economics import NOW, book, economics, evidence, market

LATER=datetime(2026,11,13,12,tzinfo=UTC)
GDP=b'<script>{"datePublished":"2026-11-12T07:00:00Z","dateModified":"2026-11-12T07:00:00Z"}</script>Release date: 12 November 2026 UK real gross domestic product (GDP) is estimated to have increased by 0.4% in Quarter 3 (July to Sept) 2026'


@pytest.fixture(autouse=True)
def controlled_available_disk(monkeypatch):
    # Fixture resource capacity is independent of the host/CI filesystem.
    monkeypatch.setattr(macro.shutil,"disk_usage",lambda _:SimpleNamespace(free=200*1024**3))


async def gdp_forecast(monkeypatch):
    e=evidence('economics')
    async def collect(**kw):return (e,)
    monkeypatch.setattr(economics,'collect',collect)
    m=market('economics');r=await economics.forecast(m,book(m),clock=lambda:NOW)
    f=r['forecasts'][0];f['id']='CONTROLLED-gdp'
    return f,{'forecasts':[f],'available_at':NOW.isoformat(),'evidence':r['evidence']}


def transport(monkeypatch,raw):
    constructor=httpx.AsyncClient
    def make(**kw):return constructor(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=raw)),**kw)
    monkeypatch.setattr(macro.httpx,'AsyncClient',make)


async def test_future_macro_does_not_touch_storage_or_http(tmp_path,monkeypatch):
    f,_s=await gdp_forecast(monkeypatch)
    def forbidden(**kw):raise AssertionError('future source must not be queried')
    monkeypatch.setattr(macro.httpx,'AsyncClient',forbidden)
    r=await macro.verify_macro_event(f,directory=tmp_path/'absent',clock=lambda:NOW)
    assert r['status']=='pending' and not r['event_result_verified'] and not (tmp_path/'absent').exists()


async def test_official_GDP_is_scorable_without_native_payout(monkeypatch,tmp_path):
    f,s=await gdp_forecast(monkeypatch);transport(monkeypatch,GDP)
    r=await macro.verify_macro_event(f,directory=tmp_path,clock=lambda:LATER)
    assert r['event_result_verified'] and not r['native_payout_verified']
    proof=macro.replay_macro_event(r,s,f,evidence_root=tmp_path,as_of=LATER)
    assert proof['outcome']==0 and proof['event_end_lower']=='2026-11-12T00:00:00+00:00' and proof['event_end_upper']=='2026-11-13T00:00:00+00:00'
    assert proof['brier']==pytest.approx(f['probability']**2) and proof['market_brier'] is None
    assert not proof['trading_authority'] and not proof['certification_authority']


@pytest.mark.parametrize('change',['identity','hash','result','future_receipt','native_claim','rules'])
async def test_GDP_result_replay_identity_hash_availability_and_authority(monkeypatch,tmp_path,change):
    f,s=await gdp_forecast(monkeypatch);transport(monkeypatch,GDP)
    r=await macro.verify_macro_event(f,directory=tmp_path,clock=lambda:LATER);bad=deepcopy(r)
    if change=='identity':bad['token_id']='CONTROLLED-other-token'
    elif change=='hash':bad['official_evidence'][0]['content_sha256']='0'*64
    elif change=='result':bad['official_result']['outcome']=1
    elif change=='future_receipt':bad['official_evidence'][0]['retrieved_at']='2027-01-01T00:00:00Z'
    elif change=='native_claim':bad['native_payout_verified']=True
    else:bad['rules_sha256']='0'*64
    with pytest.raises((ValueError,OSError)):macro.replay_macro_event(bad,s,f,evidence_root=tmp_path,as_of=LATER)


@pytest.mark.parametrize('bad',[GDP+b' Corrected release',GDP.replace(b'dateModified":"2026-11-12',b'dateModified":"2026-11-13'),GDP.replace(b'Quarter 3',b'Quarter 2')])
async def test_revised_or_wrong_quarter_never_scores(monkeypatch,tmp_path,bad):
    f,_s=await gdp_forecast(monkeypatch);transport(monkeypatch,bad)
    r=await macro.verify_macro_event(f,directory=tmp_path,clock=lambda:LATER)
    assert not r['event_result_verified'] and not r['native_payout_verified']


def final_fomc_sources(*,disagree=False):
    final=datetime(2026,12,11,21,tzinfo=UTC);out=[]
    for i,e in enumerate(fomc_evidence()):
        p=deepcopy(e.payload)
        body=p['raw_response_utf8']
        if i==0:body+='/newsevents/pressreleases/monetary20261209a.htm'
        else:body+='2026-12-08,4.5\n2026-12-09,4.5\n2026-12-10,4.5\n2026-12-11,'+('4.75' if disagree else '4.5')+'\n'
        p.update(raw_response_utf8=body,raw_response_sha256=hashlib.sha256(body.encode()).hexdigest(),raw_bytes_hex=body.encode().hex())
        out.append(e.model_copy(update={'timestamp':final,'available_at':final,'retrieved_at':final,'payload':p,'content_sha256':digest(p)}))
    return tuple(out)


async def test_calendar_linked_FOMC_statement_and_rate_corroboration(monkeypatch,tmp_path):
    from neraium_poly.research.phase24 import economics as fed
    original=fomc_evidence()
    async def collect(**kw):return original
    monkeypatch.setattr(fed,'_collect_fomc',collect)
    m=fomc_market('fomc');r=await fed.forecast(m,book(m).model_copy(update={"timestamp":original[0].timestamp,"available_at":original[0].timestamp}),clock=lambda:original[0].timestamp)
    f=r['forecasts'][0];f['id']='CONTROLLED-fomc';s={'forecasts':[f],'available_at':f['timestamp'],'evidence':r['evidence']}
    final=final_fomc_sources()
    async def current(**kw):return final
    monkeypatch.setattr(fed,'_collect_fomc',current)
    statement=b'December 9, 2026 For release at 2:00 p.m. The Committee decided to maintain the target range for the federal funds rate at 4-1/4 to 4-1/2 percent.'
    transport(monkeypatch,statement);now=datetime(2026,12,11,21,tzinfo=UTC)
    result=await macro.verify_macro_event(f,directory=tmp_path,clock=lambda:now)
    assert result['event_result_verified'],result
    proof=macro.replay_macro_event(result,s,f,evidence_root=tmp_path,as_of=now)
    assert proof['outcome']==1 and proof['event_end_lower']=='2026-12-09T19:00:00+00:00'
    assert not proof['native_payout_verified'] and proof['market_brier'] is None
    early=deepcopy(result);early['official_evidence'][2]['retrieved_at']='2026-12-08T20:00:00Z'
    with pytest.raises(ValueError,match='publication_after_receipt'):
        macro.replay_macro_event(early,s,f,evidence_root=tmp_path,as_of=now)
    alias=deepcopy(result);alias['official_evidence'][0]['source_url']='https://example.invalid/calendar'
    with pytest.raises(ValueError,match='calendar_and_target_upper'):
        macro.replay_macro_event(alias,s,f,evidence_root=tmp_path,as_of=now)
    async def wrong(**kw):return final_fomc_sources(disagree=True)
    monkeypatch.setattr(fed,'_collect_fomc',wrong)
    blocked=await macro.verify_macro_event(f,directory=tmp_path,clock=lambda:now)
    assert not blocked['event_result_verified']


def test_future_index_inventory_preserves_unresolved_and_missing_review():
    f={'id':'CONTROLLED-f','model_id':'uk-gdp-jeffreys-frequency-v25.1','domain':'economics','event_id':'e','market_id':'m','token_id':'t','timestamp':NOW.isoformat(),'event_end_time':'2026-11-12T00:00:00Z'}
    r=macro.macro_outcome_inventory([{'type':'forecast','forecast':f,'forecast_sha256':'x','available_at':NOW.isoformat(),'review':None,'replay_verified':False}],as_of=NOW)
    assert r['counts']=={'SOURCE_PROVENANCE_MISSING':1} and r['official_events_verified'] is None and not r['outcome_verification_performed']
    assert not r['trading_authority']


def test_ONS_BST_metadata_is_day_bound_not_fake_release_hour():
    contract={'quarter':2,'year':2026,'release_at':'2026-08-13T00:00:00Z','tail':'negative','lower':None,'upper':'0',
        'selected_outcome':'Yes','series_id':'IHYQ','target_period':'2026 Q2'}
    raw=GDP.replace(b'2026-11-12T07:00:00Z',b'2026-08-12T23:00:00.000Z').replace(b'12 November 2026',b'13 August 2026').replace(b'Quarter 3',b'Quarter 2')
    ref={'source_url':economics.bulletin_url(contract)}
    result=macro._final(contract,economics,[raw],[ref],datetime(2026,8,15,tzinfo=UTC))
    assert result['publication_at']=='2026-08-12T23:00:00+00:00'
    assert result['publication_upper']=='2026-08-13T23:00:00+00:00'
    assert 'not an exact release hour' in result['timing_precision']
    with pytest.raises(ValueError,match='publication_day'):
        macro._final(contract,economics,[raw],[ref],datetime(2026,8,13,12,tzinfo=UTC))


async def test_storage_floor_blocks_macro_before_any_request(monkeypatch,tmp_path):
    f,_=await gdp_forecast(monkeypatch)
    monkeypatch.setattr(macro.shutil,"disk_usage",lambda _:SimpleNamespace(free=99*1024**3))
    async def forbidden(*a,**k):raise AssertionError("no source query below floor")
    monkeypatch.setattr(macro,"_get",forbidden)
    r=await macro.verify_macro_event(f,directory=tmp_path,clock=lambda:LATER)
    assert not r['event_result_verified'] and 'filesystem_reserve' in r['reason']
    assert not list(tmp_path.iterdir())
