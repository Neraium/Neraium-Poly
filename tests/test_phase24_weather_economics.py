"""Controlled source transports/values only; fixtures are not real forecasts or outcomes."""
import csv
import hashlib
import io
import json
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24 import economics, weather

NOW=datetime(2026,11,7,22,30,tzinfo=UTC)


def market(kind='weather',threshold=18,side='Yes'):
    if kind=='weather':
        source='https://aviationweather.gov/api/data/metar?ids=ZUCK&format=raw&date=2026-11-08T19:00:00Z&hours=30'
        question=f'Will the highest temperature in Chongqing be {threshold}°C on November 8?'
        rules=weather.RULE_TEMPLATE.format(station_name='Chongqing Jiangbei International Airport',station='ZUCK',rule_day="8 Nov '26",source_url=source)
        end=NOW+timedelta(hours=13)
    elif kind=='cpi':
        source=economics.SOURCE;question='Will annual inflation be 4.0% in October?'
        rules=economics.RULE_TEMPLATE.format(month_year='October 2026',release_date='November 10, 2026');end=NOW+timedelta(days=4)
    else:
        source=economics.FOMC_CALENDAR;question='Will there be no change in Fed interest rates after the December 2026 meeting?'
        rules=economics.FOMC_RULE_TEMPLATE.format(month_year='December 2026',meeting_date='December 8-9, 2026');end=datetime(2026,12,9,23,59,tzinfo=UTC)
    return MarketSnapshot(id='CONTROLLED-'+kind,timestamp=NOW,available_at=NOW,source='https://gamma-api.polymarket.com',
        market_id=kind,event_id='CONTROLLED-event-'+kind,token_id=side,outcome=side,question=question,probability=.4,
        resolution_rules=rules,resolution_source=source,status='active',end_time=end)


def book(m):
    return OrderBookSnapshot(id='CONTROLLED-native-book',timestamp=NOW,available_at=NOW,source='https://clob.polymarket.com',
        market_id=m.market_id,token_id=m.token_id,bids=(PriceLevel(price=.4,size=100),),asks=(PriceLevel(price=.42,size=100),))


def weather_evidence():
    rows=[];zone=ZoneInfo('Asia/Shanghai');start=datetime(2026,10,11,tzinfo=zone)
    for offset in range(29):
        date=start+timedelta(days=offset)
        for hour in range(24):
            t=date+timedelta(hours=hour)
            if t>NOW:continue
            temp=12+(offset%5)+max(0,7-abs(hour-14))
            raw=f'METAR ZUCK {t.astimezone(UTC):%d%H%M}Z 00000MPS 9999 SCT030 {temp:02d}/10 Q1020'
            rows.append({'icaoId':'ZUCK','obsTime':int(t.timestamp()),'receiptTime':(t+timedelta(minutes=5)).isoformat(),'rawOb':raw})
    evidence=[]
    for end in [NOW,NOW-timedelta(days=14)]:
        selected=[r for r in rows if end-timedelta(hours=360)<=datetime.fromtimestamp(r['obsTime'],UTC)<=end]
        payload={'request_parameters':{'ids':'ZUCK','format':'json','date':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'hours':360},
                 'raw_response_utf8':json.dumps(selected),'historical_availability':'controlled fixture'}
        import httpx
        payload['request_url']=str(httpx.Request('GET',weather.ORIGIN+weather.PATH,params=payload['request_parameters']).url)
        payload['raw_response_sha256']=hashlib.sha256(payload['raw_response_utf8'].encode()).hexdigest()
        evidence.append(DomainEvidence(id=digest(payload),timestamp=NOW,available_at=NOW,source=weather.ORIGIN+weather.PATH,
            domain='weather',provider='NOAA/NWS Aviation Weather Center',source_id='ZUCK',retrieved_at=NOW,
            source_timestamp=max(datetime.fromtimestamp(r['obsTime'],UTC) for r in selected),content_sha256=digest(payload),payload=payload,
            independent_of_polymarket=True,qualification='qualified_research'))
    return tuple(evidence)


def cpi_evidence(*,gap=False):
    rows=[]
    for k in range(33):
        year,month=divmod(2024*12+k,12);month+=1
        value=str(Decimal(str(300*math.exp(.003*k+.0002*math.sin(k)))))
        row={'year':str(year),'period':f'M{month:02d}','value':value,'footnotes':[{}]}
        if gap and year==2025 and month==10:row.update(value='-',footnotes=[{'code':'X','text':'Unavailable'}])
        rows.append(row)
    raw=json.dumps({'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':economics.SERIES,'data':rows}]}})
    p={'request_url':economics.ORIGIN+economics.PATH,'raw_response_utf8':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest()}
    return (DomainEvidence(id=digest(p),timestamp=NOW,available_at=NOW,source=economics.ORIGIN+economics.PATH,domain='economics',
        provider='US Bureau of Labor Statistics',source_id=economics.SERIES,retrieved_at=NOW,content_sha256=digest(p),payload=p,
        independent_of_polymarket=True,qualification='qualified_research'),)


def fomc_evidence():
    months=['January','March','May','June','July','September','October','December'];parts=[]
    for year in range(2023,2027):
        parts.append(f'>{year} FOMC Meetings</a>')
        for month in months:
            dates='8-9' if year==2026 and month=='December' else '27-28'
            parts.append(f'<div class="fomc-meeting__month"><strong>{month}</strong></div><div class="fomc-meeting__date">{dates}</div>')
        if year==2025:parts.append('<div class="fomc-meeting__month"><strong>August</strong></div><div class="fomc-meeting__date">22 (notation vote)</div>')
    body=''.join(parts);out=io.StringIO();writer=csv.writer(out);writer.writerow(['observation_date','DFEDTARU'])
    day=datetime(2023,1,1,tzinfo=UTC)
    while day<=NOW:
        writer.writerow([day.date().isoformat(),str(Decimal(400+25*((day.toordinal()//53)%3))/100)])
        day+=timedelta(days=1)
    result=[]
    for url,provider,sid,raw in [(economics.FOMC_CALENDAR,'Board of Governors of the Federal Reserve System','fomc-calendar',body),
                               (economics.FRED_UPPER,'Federal Reserve Bank of St Louis','DFEDTARU',out.getvalue())]:
        p={'request_url':url,'raw_response_utf8':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest(),'raw_bytes_hex':raw.encode().hex()}
        result.append(DomainEvidence(id=digest(p),timestamp=NOW,available_at=NOW,source=url,domain='economics',provider=provider,source_id=sid,
            retrieved_at=NOW,content_sha256=digest(p),payload=p,independent_of_polymarket=True,qualification='qualified_research'))
    return tuple(result)


def test_weather_exact_station_day_rule_and_temperature_rounding():
    m=market();s=weather.supports(m,cutoff=NOW)
    assert s['supported'] and s['contract']['period_start']=='2026-11-07T16:00:00+00:00'
    assert weather.rounded_celsius(-8.5)==-8
    for changes in [{'resolution_source':m.resolution_source.replace('ZUCK','RKSI')},{'question':m.question.replace('Chongqing','Qingdao')},
                    {'resolution_rules':m.resolution_rules+' Clarification.'}]:
        assert not weather.supports(m.model_copy(update=changes),cutoff=NOW)['supported']


def test_weather_actual_variable_models_reproduce_and_are_uncalibrated():
    c=weather.supports(market(),cutoff=NOW)['contract'];e=weather_evidence();rows=weather.estimate(c,e,cutoff=NOW)
    assert len(rows)==2 and all(r['training_observations']==28 for r in rows)
    assert [r['probability'] for r in rows]==[r['probability'] for r in weather.estimate(c,e,cutoff=NOW)]
    assert all(r['lower_probability']==0 and r['upper_probability']==1 and not r['unconditional_contract_probability'] for r in rows)
    assert not any(r['trading_authority'] for r in rows)


@pytest.mark.parametrize('kind',['source_future','raw_corrupt','wrong_query_station','missing_day','special_only'])
def test_weather_missing_noncausal_or_inconsistent_evidence_withheld(kind):
    c=weather.supports(market(),cutoff=NOW)['contract'];e=list(weather_evidence())
    if kind=='source_future':e[0]=e[0].model_copy(update={'available_at':NOW+timedelta(seconds=1)})
    elif kind=='raw_corrupt':e[0]=e[0].model_copy(update={'content_sha256':'0'*64})
    else:
        ev=e[0];p=deepcopy(ev.payload)
        if kind=='wrong_query_station':p['request_url']=p['request_url'].replace('ZUCK','ZSQD')
        else:
            for i,ev in enumerate(e):
                p=deepcopy(ev.payload);rows=json.loads(p['raw_response_utf8'])
                if kind=='missing_day':rows=[x for x in rows if datetime.fromtimestamp(x['obsTime'],ZoneInfo('Asia/Shanghai')).hour!=14]
                else:
                    for row in rows:row['rawOb']='SPECI '+row['rawOb']
                p['raw_response_utf8']=json.dumps(rows);p['raw_response_sha256']=hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest()
                e[i]=ev.model_copy(update={'payload':p,'content_sha256':digest(p)})
            p=None
        if p is not None:e[0]=ev.model_copy(update={'payload':p,'content_sha256':digest(p)})
    with pytest.raises(ValueError):weather.estimate(c,e,cutoff=NOW)


def test_weather_already_exceeded_bin_not_new_prediction():
    m=market(threshold=5);c=weather.supports(m,cutoff=NOW)['contract']
    with pytest.raises(ValueError,match='already_exceeded'):weather.estimate(c,weather_evidence(),cutoff=NOW)


async def test_weather_forecast_replay_and_unchanged_price_independence(monkeypatch):
    e=weather_evidence()
    async def collect(*args,**kwargs):return e
    monkeypatch.setattr(weather,'collect',collect)
    m=market();b=book(m);r=await weather.forecast(m.model_dump(),b.model_dump(),clock=lambda:NOW)
    assert len(r['forecasts'])==2
    for row in r['forecasts']:
        assert row['market_probability'] is None and row['market_expected_payout']==pytest.approx(.41)
        assert weather.replay(row,r['evidence'],as_of=NOW)['verified']
        row['probability']=1-row['probability']
        with pytest.raises(ValueError):weather.replay(row,r['evidence'],as_of=NOW)
    stale=b.model_copy(update={'timestamp':NOW-timedelta(minutes=1),'available_at':NOW-timedelta(minutes=1)})
    assert not (await weather.forecast(m.model_dump(),stale.model_dump(),clock=lambda:NOW))['forecasts']


def test_cpi_missing_actual_year_ago_index_never_imputed():
    m=market('cpi');c=economics.supports(m,cutoff=NOW)['contract']
    with pytest.raises(ValueError,match='year_ago_CPI_index_unavailable'):economics._estimate_cpi(c,cpi_evidence(gap=True),cutoff=NOW)
    rows=economics._estimate_cpi(c,cpi_evidence(),cutoff=NOW)
    assert len(rows)==2 and all(0<=r['probability']<=1 and not r['trading_authority'] for r in rows)


def test_cpi_future_snapshot_and_wrong_series_deny():
    m=market('cpi');c=economics.supports(m,cutoff=NOW)['contract'];e=cpi_evidence()[0]
    with pytest.raises(ValueError):economics._estimate_cpi(c,(e.model_copy(update={'available_at':NOW+timedelta(seconds=1)}),),cutoff=NOW)
    p=deepcopy(e.payload);p['raw_response_utf8']=p['raw_response_utf8'].replace('CUUR0000SA0','CUSR0000SA0');p['raw_response_sha256']=hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest()
    with pytest.raises(ValueError):economics._estimate_cpi(c,(e.model_copy(update={'payload':p,'content_sha256':digest(p)}),),cutoff=NOW)


def test_fomc_calendar_target_upper_meetings_and_notation_vote():
    c=economics.supports(market('fomc'),cutoff=NOW)['contract'];e=fomc_evidence();rows=economics._estimate_fomc(c,e,cutoff=NOW)
    assert len(rows)==2 and all(r['training_observations']==31 for r in rows)
    assert '2025-08-22' not in [x['date'] for x in rows[0]['historical_meeting_changes']]
    assert all(not r['unconditional_contract_probability'] and not r['trading_authority'] for r in rows)
    changed=market('fomc').model_copy(update={'resolution_rules':market('fomc').resolution_rules.replace('upper bound','effective rate')})
    assert not economics.supports(changed,cutoff=NOW)['supported']


@pytest.mark.parametrize('change',['future','effective_not_target','calendar_missing','raw_corrupt'])
def test_fomc_identity_and_availability_fail_closed(change):
    c=economics.supports(market('fomc'),cutoff=NOW)['contract'];e=list(fomc_evidence())
    if change=='future':e[0]=e[0].model_copy(update={'available_at':NOW+timedelta(days=1)})
    elif change=='raw_corrupt':e[0]=e[0].model_copy(update={'content_sha256':'0'*64})
    else:
        index=1 if change=='effective_not_target' else 0;ev=e[index];p=deepcopy(ev.payload)
        p['raw_response_utf8']=p['raw_response_utf8'].replace('DFEDTARU','DFF') if change=='effective_not_target' else p['raw_response_utf8'].replace('8-9','8-10')
        p['raw_bytes_hex']=p['raw_response_utf8'].encode().hex();p['raw_response_sha256']=hashlib.sha256(bytes.fromhex(p['raw_bytes_hex'])).hexdigest()
        e[index]=ev.model_copy(update={'payload':p,'content_sha256':digest(p)})
    with pytest.raises(ValueError):economics._estimate_fomc(c,e,cutoff=NOW)


async def test_fomc_prospective_full_replay_no_market_probability_dependency(monkeypatch):
    e=fomc_evidence()
    async def collect(**kwargs):return e
    monkeypatch.setattr(economics,'_collect_fomc',collect)
    m=market('fomc');b=book(m);r=await economics.forecast(m.model_dump(),b.model_dump(),clock=lambda:NOW)
    assert len(r['forecasts'])==2
    for row in r['forecasts']:
        assert row['market_probability'] is None and economics.replay(row,r['evidence'],as_of=NOW)['verified']
    changed=m.model_copy(update={'probability':.91})
    other=await economics.forecast(changed.model_dump(),b.model_dump(),clock=lambda:NOW)
    assert [x['probability'] for x in r['forecasts']]==[x['probability'] for x in other['forecasts']]


async def test_pending_domain_outcomes_never_get_a_label():
    w={'contract':weather.supports(market(),cutoff=NOW)['contract']}
    e={'contract':economics.supports(market('fomc'),cutoff=NOW)['contract']}
    assert not (await weather.verify_outcome(w,directory='unused-controlled',clock=lambda:NOW))['verified']
    assert not (await economics.verify_outcome(e,directory='unused-controlled',clock=lambda:NOW))['verified']


async def test_weather_final_reference_requires_native_proof_and_freeze(monkeypatch,tmp_path):
    import httpx
    from neraium_poly.research.phase12 import outcome_collector

    m=market();c=weather.supports(m,cutoff=NOW)['contract'];zone=ZoneInfo(c['timezone']);start=datetime.fromisoformat(c['period_start'])
    rows=[]
    for hour in range(25):
        t=start+timedelta(hours=hour);local=t.astimezone(zone);temp=18 if hour<24 else 17
        rows.append({'icaoId':'ZUCK','obsTime':int(t.timestamp()),'receiptTime':(t+timedelta(minutes=5)).isoformat(),
                     'rawOb':f'METAR ZUCK {local:%d%H%M}Z 00000MPS 9999 SCT030 {temp:02d}/10 Q1020'})
    class Client:
        def __init__(self,*a,**k):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def get(self,url,params):return httpx.Response(200,json=rows,request=httpx.Request('GET',url,params=params))
    monkeypatch.setattr(weather.httpx,'AsyncClient',Client)
    called=[]
    async def missing(*args,**kwargs):called.append(True);
    monkeypatch.setattr(outcome_collector,'acquire_verified_outcome',missing)
    f={'id':'CONTROLLED forecast','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,'timestamp':NOW.isoformat(),
       'evidence_cutoff':NOW.isoformat(),'rules_sha256':c['rules_sha256'],'market':m.model_dump(mode='json'),'contract':c}
    later=datetime.fromisoformat(c['period_end'])+timedelta(hours=4)
    result=await weather.verify_outcome(f,directory=tmp_path,clock=lambda:later)
    assert not result['verified'] and result['reason']=='native_finalized_weather_proof_pending' and called
    called.clear();rows[2]['receiptTime']=(start+timedelta(hours=26)).isoformat()
    result=await weather.verify_outcome(f,directory=tmp_path,clock=lambda:later)
    assert not result['verified'] and result['reason']=='post_freeze_corrections_ambiguous' and not called


async def test_economic_official_firstrelease_403_does_not_become_label(monkeypatch,tmp_path):
    import httpx
    m=market('cpi');c=economics.supports(m,cutoff=NOW)['contract']
    class Client:
        def __init__(self,*a,**k):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def get(self,url):return httpx.Response(403,request=httpx.Request('GET',url))
    monkeypatch.setattr(economics.httpx,'AsyncClient',Client)
    result=await economics.verify_outcome({'contract':c},directory=tmp_path,clock=lambda:NOW+timedelta(days=4))
    assert not result['verified'] and result['http_status']==403


async def test_weather_offline_outcome_replays_model_source_and_native_boundary(monkeypatch,tmp_path):
    import httpx
    from neraium_poly.research.phase12 import outcome_collector
    from neraium_poly.research.phase12.contracts import VerifiedEventOutcome

    async def collect(*a,**k):return weather_evidence()
    monkeypatch.setattr(weather,'collect',collect)
    m=market();r=await weather.forecast(m.model_dump(),book(m).model_dump(),clock=lambda:NOW)
    f=r['forecasts'][0];f['id']='CONTROLLED-original-forecast'
    study={'id':'CONTROLLED-original-study','available_at':NOW.isoformat(),'forecasts':[f],'evidence':r['evidence']}
    end=datetime.fromisoformat(f['contract']['period_end']);received=end+timedelta(hours=4);settled=end+timedelta(minutes=10)
    rows=[]
    for h in range(25):
        t=end-timedelta(days=1)+timedelta(hours=h)
        rows.append({'icaoId':'ZUCK','obsTime':int(t.timestamp()),'receiptTime':(t+timedelta(minutes=5)).isoformat(),
            'rawOb':f'METAR ZUCK {t:%d%H%M}Z 00000MPS 9999 SCT030 18/10 Q1020'})
    raw=json.dumps(rows);url=str(httpx.Request('GET',weather.ORIGIN+weather.PATH,params={'ids':'ZUCK','format':'json','date':'2026-11-08T19:00:00Z','hours':30}).url)
    proof=VerifiedEventOutcome(id='CONTROLLED-proof',timestamp=settled,available_at=received,source='CONTROLLED-native-boundary',
        event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],payout=1,resolution_rules_sha256=f['rules_sha256'],
        settled_at=settled,verification_source='CONTROLLED',proof_sha256='0'*64,verification={})
    result={'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'outcome':1,'resolved_at':settled.isoformat(),
        'available_at':received.isoformat(),'proof':proof.model_dump(mode='json'),
        'evidence':[{'request_url':url,'raw_response_utf8':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest(),'retrieved_at':received.isoformat()}]}
    # Asserted flags are insufficient without actual native evidence.
    with pytest.raises(ValueError):weather.replay_outcome(result,study,f,evidence_root=tmp_path,as_of=received)
    monkeypatch.setattr(outcome_collector,'verify_collected_outcome',lambda *a:True) # Controlled engineering boundary only.
    score=weather.replay_outcome(result,study,f,evidence_root=tmp_path,as_of=received)
    assert score['verified'] and score['market_brier'] is None and score['brier']==(1-f['probability'])**2
    bad=deepcopy(result);bad['evidence'][0]['raw_response_sha256']='f'*64
    with pytest.raises(ValueError):weather.replay_outcome(bad,study,f,evidence_root=tmp_path,as_of=received)
    bad=deepcopy(result);bad['outcome']=0
    with pytest.raises(ValueError):weather.replay_outcome(bad,study,f,evidence_root=tmp_path,as_of=received)


def test_official_fomc_statement_parser_checks_level_action_and_publication():
    evidence=list(fomc_evidence());later=datetime(2026,12,12,22,tzinfo=UTC);day=datetime(2026,12,9,tzinfo=UTC)
    ev=evidence[1];p=deepcopy(ev.payload);p['raw_response_utf8']+=''.join((day+timedelta(days=i)).date().isoformat()+',4.00\r\n' for i in range(-1,3))
    # Replace all source values with constant4.00 so this controlled statement is coherent.
    reader=list(csv.reader(io.StringIO(p['raw_response_utf8'])));body=io.StringIO();writer=csv.writer(body);writer.writerow(reader[0])
    seen=set()
    for date,_value in reader[1:]:
        if date not in seen:writer.writerow([date,'4.00']);seen.add(date)
    writer.writerow(['2026-12-12','4.00'])
    p['raw_response_utf8']=body.getvalue();p['raw_bytes_hex']=p['raw_response_utf8'].encode().hex();p['raw_response_sha256']=hashlib.sha256(bytes.fromhex(p['raw_bytes_hex'])).hexdigest()
    evidence[1]=ev.model_copy(update={'payload':p,'content_sha256':digest(p),'timestamp':later,'available_at':later,'retrieved_at':later})
    c=economics.supports(market('fomc'),cutoff=NOW)['contract']
    statement=b'December 9, 2026 For release at 2:00 p.m. EST The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent.'
    assert economics._final_fomc(c,evidence,statement,later)['expected']==1
    wrong=statement.replace(b'3-3/4 to 4 percent',b'3-1/2 to 3-3/4 percent')
    assert not economics._final_fomc(c,evidence,wrong,later)['verified']
    wrong=statement.replace(b'December 9, 2026',b'December 8, 2026')
    assert not economics._final_fomc(c,evidence,wrong,later)['verified']
