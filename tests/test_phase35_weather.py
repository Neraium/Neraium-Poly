"""Controlled fixtures only; no fixture forecasts or outcomes count as evidence."""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase35 import weather

NOW=datetime(2026,11,9,0,30,tzinfo=UTC)


def market(side='Yes'):
 source=weather.ORIGIN+weather.PATH+'?ids=ZBAA&format=raw&date=2026-11-10T19:00:00Z&hours=30'
 return MarketSnapshot(id='CONTROLLED-weather',timestamp=NOW,available_at=NOW,source='https://gamma-api.polymarket.com',market_id='CONTROLLED-M',event_id='CONTROLLED-E',token_id=side,outcome=side,question='Will the highest temperature in Beijing be 18°C on November 10?',probability=.4,resolution_rules=weather.legacy.RULE_TEMPLATE.format(station_name=weather.STATIONS['ZBAA']['name'],station='ZBAA',rule_day="10 Nov '26",source_url=source),resolution_source=source,status='active',end_time=datetime(2026,11,10,16,tzinfo=UTC))


def book(m):
 return OrderBookSnapshot(id='CONTROLLED-book',timestamp=NOW,available_at=NOW,source='https://clob.polymarket.com',market_id=m.market_id,token_id=m.token_id,bids=(PriceLevel(price=.4,size=100),),asks=(PriceLevel(price=.42,size=100),))


def evidence(*,missing=None):
 rows=[];start=(NOW-timedelta(days=37)).replace(minute=0)
 for i in range(37*24+1):
  t=start+timedelta(hours=i)
  if t>NOW:continue
  if missing and t==missing:continue
  temp=10+t.day%5+max(0,7-abs((t.hour+8)%24-14))
  rows.append({'icaoId':'ZBAA','obsTime':int(t.timestamp()),'receiptTime':(t+timedelta(minutes=5)).isoformat(),'rawOb':f'METAR ZBAA {t:%d%H%M}Z 00000MPS 9999 SCT030 {temp:02d}/10 Q1020'})
 result=[]
 for offset in (0,7,14):
  end=NOW-timedelta(days=offset);selected=[r for r in rows if end-timedelta(hours=360)<=datetime.fromtimestamp(r['obsTime'],UTC)<=end];q={'ids':'ZBAA','format':'json','date':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'hours':360};raw=json.dumps(selected)
  p={'request_parameters':q,'request_url':str(httpx.Request('GET',weather.ORIGIN+weather.PATH,params=q).url),'raw_response_utf8':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest()}
  result.append(DomainEvidence(id=digest(p),timestamp=NOW,available_at=NOW,source=weather.ORIGIN+weather.PATH,domain='weather',provider='NOAA/NWS Aviation Weather Center',source_id='ZBAA',retrieved_at=NOW,source_timestamp=max(datetime.fromtimestamp(r['obsTime'],UTC) for r in selected),content_sha256=digest(p),payload=p,independent_of_polymarket=True,qualification='qualified_research'))
 raw=json.dumps([{'icaoId':'ZBAA','country':'CN','site':'Beijing Intl','siteType':['METAR','TAF']}]);p={'request_url':weather.ORIGIN+weather.STATION_PATH+'?ids=ZBAA&format=json','raw_response_utf8':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest()}
 result.append(DomainEvidence(id=digest(p),timestamp=NOW,available_at=NOW,source=weather.ORIGIN+weather.STATION_PATH,domain='weather',provider='NOAA/NWS Aviation Weather Center',source_id='ZBAA',retrieved_at=NOW,content_sha256=digest(p),payload=p,independent_of_polymarket=True,qualification='qualified_research'))
 return tuple(result)


def test_exact_reviewed_station_rules_and_preday_window():
 m=market();r=weather.supports(m,cutoff=NOW);assert r['supported']
 assert not weather.supports(m.model_copy(update={'question':m.question.replace('Beijing','Shanghai')}),cutoff=NOW)['supported']
 assert not weather.supports(m.model_copy(update={'resolution_rules':m.resolution_rules+' extra'}),cutoff=NOW)['supported']
 assert not weather.supports(m,cutoff=datetime(2026,11,9,16,tzinfo=UTC))['supported']
 assert not weather.supports(m,cutoff=NOW-timedelta(seconds=1))['supported']


def test_fixed_calendar_cohort_and_uncertainty_not_confidence_or_native_profit():
 m=market();c=weather.supports(m,cutoff=NOW)['contract'];values=weather.estimate(c,evidence(),cutoff=NOW)
 assert len(values)==2
 for f in values:
  assert f['training_observations']==21 and len(f['training_days'])==21
  assert f['training_days'][-1]=='2026-11-08' and f['training_days'][0]=='2026-10-19'
  assert f['probability']==pytest.approx(f['hits']/21 if f['model_id']==weather.MODELS[0] else (f['hits']+.5)/22)
  assert f['lower_probability']==0 and f['upper_probability']==1 and not f['unconditional_contract_probability']
  assert not f['trading_authority'] and not f['certification_authority'] and len(f['source_lineages'])==1
 c_no=weather.supports(market('No'),cutoff=NOW)['contract'];other=weather.estimate(c_no,evidence(),cutoff=NOW)
 assert all(a['probability']+b['probability']==pytest.approx(1) for a,b in zip(values,other,strict=True))


def test_missing_hours_withhold_instead_of_selecting_more_favourable_complete_days():
 m=market();c=weather.supports(m,cutoff=NOW)['contract'];missing=datetime(2026,11,3,4,tzinfo=UTC)
 raw=evidence(missing=missing);rows=weather.observations(c,raw,cutoff=NOW);cohort=weather.calendar_cohort(c,rows,cutoff=NOW)
 assert not cohort['complete'] and len(cohort['coverage'])==21
 with pytest.raises(ValueError,match='fixed21_calendar'):weather.estimate(c,raw,cutoff=NOW)


@pytest.mark.parametrize('fault',['future','station_metadata','history_hash','history_station','raw_time','missing_metadata'])
def test_provenance_corruption_and_future_inputs_never_produce_probabilities(fault):
 m=market();c=weather.supports(m,cutoff=NOW)['contract'];raw=[x.model_dump(mode='json') for x in evidence()]
 if fault=='future':raw[0]['available_at']=(NOW+timedelta(seconds=1)).isoformat()
 if fault=='station_metadata':
  p=raw[-1]['payload'];p['raw_response_utf8']=p['raw_response_utf8'].replace('Beijing Intl','Wrong Airport');p['raw_response_sha256']=hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest();raw[-1]['content_sha256']=digest(p)
 if fault=='history_hash':raw[0]['payload']['raw_response_sha256']='0'*64
 if fault in ('history_station','raw_time'):
  p=raw[0]['payload'];rs=json.loads(p['raw_response_utf8']);rs[0]['icaoId']='OTHER' if fault=='history_station' else rs[0]['icaoId'];rs[0]['rawOb']=rs[0]['rawOb'].replace('Z 00000','Z 00000') if fault=='history_station' else rs[0]['rawOb'].replace('ZBAA ','ZBAA 000000Z ',1);p['raw_response_utf8']=json.dumps(rs);p['raw_response_sha256']=hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest();raw[0]['content_sha256']=digest(p)
 if fault=='missing_metadata':raw.pop()
 with pytest.raises(ValueError):weather.estimate(c,raw,cutoff=NOW)


async def test_prospective_forecast_replays_exact_model_book_and_market_baseline(monkeypatch):
 m=market();b=book(m)
 async def collect(*args,**kwargs):return evidence()
 monkeypatch.setattr(weather,'collect',collect)
 r=await weather.forecast(m,b,clock=lambda:NOW);assert len(r['forecasts'])==2
 for f in r['forecasts']:
  f['id']=digest(f);assert weather.replay(f,r['evidence'],as_of=NOW)['verified']
  broken=deepcopy(f);broken['probability']+=.01
  with pytest.raises(ValueError,match='replay_mismatch'):weather.replay(broken,r['evidence'],as_of=NOW)
  broken=deepcopy(f);broken['book']['asks'][0]['size']+=1
  with pytest.raises(ValueError,match='quote_binding'):weather.replay(broken,r['evidence'],as_of=NOW)
  broken=deepcopy(f);broken['market_expected_payout']+=.01
  with pytest.raises(ValueError,match='baseline_mismatch'):weather.replay(broken,r['evidence'],as_of=NOW)
