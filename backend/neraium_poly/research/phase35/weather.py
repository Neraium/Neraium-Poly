"""Prospective pre-day AWC baselines for reviewed additional Chinese stations.

Independent station histories, not market-price features. These are conditional
reference probabilities with unvalidated uncertainty; never native payout or
execution authority. The 21-calendar-day cohort is frozen before predictions:
missing hours withhold a model instead of selecting only favourable full days.
"""
import asyncio
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase14.weather import _temperature, rounded_celsius
from neraium_poly.research.phase24 import weather as legacy
from neraium_poly.research.phase25.dependencies import at

ORIGIN=legacy.ORIGIN
PATH=legacy.PATH
STATION_PATH='/api/data/stationinfo'
STATIONS={
 'ZBAA':{'city':'Beijing','name':'Beijing Capital International Airport','site':'Beijing Intl','timezone':'Asia/Shanghai'},
 'ZSPD':{'city':'Shanghai','name':'Shanghai Pudong International Airport','site':'Shanghai/Pudong Intl','timezone':'Asia/Shanghai'},
 'ZGSZ':{'city':'Shenzhen','name':"Shenzhen Bao'an International Airport",'site':'Shenzhen/Boan Intl','timezone':'Asia/Shanghai'},
}
MODELS=('awc-calendar-frequency-v35.1','awc-jeffreys-frequency-v35.1')
_CACHE={}


def definitions():
 sha=digest([Path(__file__).read_text(),Path(legacy.__file__).read_text()])
 return [{'model_id':m,'model_version':m,'model_sha256':digest([sha,m]),'feature_version':'fixed-21-prior-calendar-days-v35',
   'domain':'weather','hypothesis':h,'input_requirements':['exact reviewed AWC station/rules','verified station metadata','all hours in21 preceding complete calendar days','forecast before event local day starts'],
   'performance_criteria':['prospective exact-reference Brier/log loss','event-disjoint chronological validation','no market comparison without compatible native target'],
   'risk_assumptions':'Unvalidated recent-day exchangeability/seasonality; conditional on ordinary reference availability and no material corrections',
   'failure_conditions':['missing calendar-day hours','station identity changes','climate regime change','AWC correction or fallback'],
   'source_independence':'Both baselines share NOAA/AWC lineage, not independent corroboration',
   'research_only':True,'trading_authority':False,'certification_authority':False}
   for m,h in zip(MODELS,['Empirical frequency on21 fixed preceding calendar-day station highs','Jeffreys beta-binomial posterior mean on the identical frozen calendar cohort'],strict=True)]


def supports(market,*,cutoff):
 try:
  now=at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if isinstance(market,MarketSnapshot) else market)
  if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
      or max(m.timestamp,m.available_at)>now or m.outcome not in {'Yes','No'} or not m.end_time or m.end_time<=now):raise ValueError('causal_active_weather_market_required')
  match=re.fullmatch(r'Will the highest temperature in (Beijing|Shanghai|Shenzhen) be (-?\d{1,2})°C(?: or (higher|below))? on ([A-Z][a-z]+ \d{1,2})\?',m.question)
  if match is None:raise ValueError('unsupported_pre_day_weather_question')
  city,k,tail,date=match.groups();u=urlsplit(m.resolution_source);q=parse_qs(u.query)
  if u.scheme!='https' or u.netloc!='aviationweather.gov' or u.path!=PATH or set(q)!={'ids','format','date','hours'}:raise ValueError('exact_AWC_resolution_reference_required')
  station=q['ids'][0];spec=STATIONS.get(station)
  if not spec or spec['city']!=city or q['format']!=['raw'] or q['hours']!=['30']:raise ValueError('reviewed_station_window_required')
  source_end=at(q['date'][0]);zone=ZoneInfo(spec['timezone']);day=(source_end.astimezone(zone)-timedelta(days=1)).date();start=datetime.combine(day,datetime.min.time(),zone).astimezone(UTC);end=start+timedelta(days=1)
  if source_end!=end+timedelta(hours=3) or datetime.strptime(f'{day.year} {date}','%Y %B %d').date()!=day:raise ValueError('exact_station_local_date_required')
  if not start-timedelta(days=1)<=now<start:raise ValueError('pre_day_forecast_window_required')
  if not -80<=int(k)<=60:raise ValueError('reviewed_weather_threshold_required')
  expected=legacy.RULE_TEMPLATE.format(station_name=spec['name'],station=station,rule_day=day.strftime("%-d %b '%y"),source_url=m.resolution_source)
  if m.resolution_rules!=expected:raise ValueError('weather_resolution_rule_template_mismatch')
  return {'supported':True,'reasons':[],'contract':{'station':station,**spec,'day':day.isoformat(),'period_start':start.isoformat(),'period_end':end.isoformat(),'threshold':int(k),'tail':tail,'selected_outcome':m.outcome,'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),'source_url':m.resolution_source,'market':m.model_dump(mode='json')}}
 except (ValueError,TypeError,KeyError,IndexError) as error:return {'supported':False,'reasons':[str(error)[:160]],'contract':None}


async def station_metadata(station,*,clock):
 async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
  response=await client.get(ORIGIN+STATION_PATH,params={'ids':station,'format':'json'});response.raise_for_status();raw=response.content
 if not 0<len(raw)<=64*1024:raise ValueError('bounded_station_metadata_required')
 received=at(clock());payload={'request_url':str(response.url),'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'availability':'first verified retrieval; no historical vintage asserted'}
 return DomainEvidence(id=digest(['AWC-station-identity-v35',payload,received.isoformat()]),timestamp=received,available_at=received,source=ORIGIN+STATION_PATH,domain='weather',provider='NOAA/NWS Aviation Weather Center',source_id=station,retrieved_at=received,source_timestamp=None,content_sha256=digest(payload),payload=payload,independent_of_polymarket=True,qualification='qualified_research')


async def collect(contract,*,clock):
 station=contract['station'];now=at(clock());cached=_CACHE.get(station)
 if cached and 0<=(now-cached[-1].available_at).total_seconds()<300:return cached
 # Overlapping seven-day offsets preserve half-hourly stations despite the
 # provider's400-row response cap; no absent historical observations are filled.
 records=[await legacy._fetch(station,now-timedelta(days=days),clock) for days in (0,7,14)]
 records.append(await station_metadata(station,clock=clock));_CACHE[station]=tuple(records)
 return _CACHE[station]


def observations(contract,evidence,*,cutoff):
 cutoff=at(cutoff);station=contract['station'];values=[DomainEvidence.model_validate(e.model_dump() if isinstance(e,DomainEvidence) else e) for e in evidence]
 if len(values)!=4:raise ValueError('three_history_chunks_and_station_metadata_required')
 by_time={}
 for e in values:
  p=e.payload
  if (e.domain!='weather' or e.provider!='NOAA/NWS Aviation Weather Center' or e.source_id!=station or not e.independent_of_polymarket or e.qualification!='qualified_research'
      or max(e.timestamp,e.available_at,e.retrieved_at)>cutoff or digest(p)!=e.content_sha256 or hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest()!=p['raw_response_sha256']):raise ValueError('causal_exact_station_raw_provenance_required')
 for e in values[:3]:
  p=e.payload;query=p['request_parameters'];u=urlsplit(p['request_url'])
  if (e.source!=ORIGIN+PATH or u.scheme!='https' or u.netloc!='aviationweather.gov' or u.path!=PATH or query['ids']!=station or query['format']!='json' or query['hours']!=360 or at(query['date'])>e.retrieved_at or parse_qs(u.query)!={k:[str(v)] for k,v in query.items()}):raise ValueError('AWC_history_query_identity_required')
  rows=json.loads(p['raw_response_utf8'])
  if not isinstance(rows,list) or not 1<=len(rows)<=400:raise ValueError('bounded_history_chunk_required')
  if e.source_timestamp!=max(datetime.fromtimestamp(r['obsTime'],UTC) for r in rows):raise ValueError('AWC_history_source_timestamp_mismatch')
  for r in rows:
   obs=datetime.fromtimestamp(r['obsTime'],UTC);receipt=at(r['receiptTime']);raw=r['rawOb'].strip()
   if r['icaoId']!=station or max(obs,receipt)>e.available_at or not at(query['date'])-timedelta(hours=360)<=obs<=at(query['date']):raise ValueError('noncausal_or_wrong_station_observation')
   if raw.startswith('SPECI'):continue
   match=re.match(r'^(?:METAR\s+)?'+re.escape(station)+r'\s+(\d{6})Z\s',raw)
   if match is None or match[1]!=obs.strftime('%d%H%M'):raise ValueError('raw_station_observation_timestamp_mismatch')
   temperature=float(_temperature(raw)[0])
   if not -80<=temperature<=60:raise ValueError('implausible_station_temperature')
   item={'at':obs.isoformat(),'temperature':temperature,'received_at':receipt.isoformat(),'raw':raw};prior=by_time.get(obs)
   if prior and prior['received_at']==item['received_at'] and prior['raw']!=raw:raise ValueError('conflicting_routine_station_versions')
   if prior is None or at(prior['received_at'])<receipt:by_time[obs]=item
 meta=values[-1];u=urlsplit(meta.payload['request_url']);rows=json.loads(meta.payload['raw_response_utf8'])
 if (meta.source!=ORIGIN+STATION_PATH or u.scheme!='https' or u.netloc!='aviationweather.gov' or u.path!=STATION_PATH or parse_qs(u.query)!={'ids':[station],'format':['json']} or not isinstance(rows,list) or len(rows)!=1):raise ValueError('exact_station_metadata_reference_required')
 row=rows[0]
 if row.get('icaoId')!=station or row.get('country')!='CN' or row.get('site')!=contract['site'] or 'METAR' not in row.get('siteType',[]):raise ValueError('reviewed_official_station_identity_required')
 if not by_time or (cutoff-max(at(t) for t in by_time)).total_seconds()>5400:raise ValueError('current_station_history_stale')
 return [by_time[t] for t in sorted(by_time)]


def calendar_cohort(contract,rows,*,cutoff):
 zone=ZoneInfo(contract['timezone']);day=at(cutoff).astimezone(zone).date();grouped=defaultdict(list)
 for row in rows:grouped[at(row['at']).astimezone(zone).date()].append(row)
 expected=[day-timedelta(days=i) for i in range(21,0,-1)];coverage=[]
 for d in expected:
  hours={at(r['at']).astimezone(zone).hour for r in grouped[d]};coverage.append({'day':d.isoformat(),'observed_hours':len(hours),'missing_hours':sorted(set(range(24))-hours)})
 return {'calendar_days':[d.isoformat() for d in expected],'coverage':coverage,'complete':all(not d['missing_hours'] for d in coverage),'highs':[max(r['temperature'] for r in grouped[d]) for d in expected] if all(grouped[d] for d in expected) else None}


def estimate(contract,evidence,*,cutoff):
 cutoff=at(cutoff);m=MarketSnapshot.model_validate(contract['market']);mapped=supports(m,cutoff=cutoff)
 if not mapped['supported'] or mapped['contract']!=contract:raise ValueError('exact_pre_day_contract_replay_required')
 rows=observations(contract,evidence,cutoff=cutoff);cohort=calendar_cohort(contract,rows,cutoff=cutoff)
 if not cohort['complete']:raise ValueError('fixed21_calendar_day_hour_coverage_required')
 threshold=contract['threshold'];tail=contract['tail']
 def matches(x):
  value=rounded_celsius(x)
  return value>=threshold if tail=='higher' else value<=threshold if tail=='below' else value==threshold
 hits=sum(matches(x) for x in cohort['highs']);n=len(cohort['calendar_days']);result=[]
 for definition,yes in zip(definitions(),(hits/n,(hits+.5)/(n+1)),strict=True):
  probability=yes if contract['selected_outcome']=='Yes' else 1-yes
  result.append({**definition,'domain':'weather','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,'probability':probability,'probability_semantics':'binary_event_probability',
   'lower_probability':0.,'upper_probability':1.,'uncertainty':{'type':'uncalibrated_model_policy_not_confidence_interval','lower_probability':0.,'upper_probability':1.},
   'evidence_cutoff':cutoff.isoformat(),'event_end_time':contract['period_end'],'rules_sha256':contract['rules_sha256'],'evidence_ids':[e.id if hasattr(e,'id') else e['id'] for e in evidence],
   'source_lineages':['NOAA/AWC:'+contract['station']],'training_days':cohort['calendar_days'],'training_observations':n,'calendar_coverage':cohort['coverage'],'hits':hits,
   'dataset_sha256':digest(rows),'contract':contract,'independent_of_polymarket':True,'calibration_status':'unvalidated_research','conditioning':'routine AWC availability and no material correction/fallback',
   'unconditional_contract_probability':False,'limitations':['Recent-calendar exchangeability is unvalidated','Multiple models/chunks share one provider lineage','Historical raw observations first retrieved now; not a historical vintage or out-of-sample result'],
   'research_only':True,'trading_authority':False,'certification_authority':False})
 return result


async def discover(*,clock):
 from neraium_poly.research.phase25.finance import _discover
 return await _discover(('highest temperature in Beijing','highest temperature in Shanghai','highest temperature in Shenzhen'),clock=clock)


async def forecast(market,book,*,clock):
 m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market);mapped=supports(m,cutoff=at(clock()))
 if not mapped['supported']:return {'forecasts':[],'evidence':[],'rejections':mapped['reasons']}
 evidence=()
 try:
  evidence=await collect(mapped['contract'],clock=clock);cutoff=at(clock());b=OrderBookSnapshot.model_validate(book.model_dump() if hasattr(book,'model_dump') else book) if book is not None else None
  if b is None or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy:
   adapter=OperationalPolymarketAdapter(clock=clock)
   try:b=await adapter.book(m.market_id,m.token_id)
   finally:await adapter.close()
  cutoff=at(clock())
  if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or b.exchange!=m.exchange or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('fresh_native_two_sided_weather_book_required')
  values=await asyncio.to_thread(estimate,mapped['contract'],evidence,cutoff=cutoff);created=at(clock())
  if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('weather_book_stale_after_model')
  for f in values:f.update(timestamp=created.isoformat(),market=m.model_dump(mode='json'),book=b.model_dump(mode='json'),book_id=b.id,book_sha256=digest(b.model_dump(mode='json')),market_probability=None,market_expected_payout=(b.bids[0].price+b.asks[0].price)/2)
  return {'forecasts':values,'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
 except (ValueError,TypeError,KeyError,httpx.HTTPError) as error:return {'forecasts':[],'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[str(error)[:180]]}


def replay(forecast,evidence,*,as_of):
 f=forecast;cutoff=at(f['evidence_cutoff']);created=at(f['timestamp'])
 if not cutoff<=created<=at(as_of):raise ValueError('prospective_weather_cutoff_required')
 selected=[DomainEvidence.model_validate(e) for e in evidence if e['id'] in f['evidence_ids']]
 if len(set(f['evidence_ids']))!=len(f['evidence_ids']) or len({e.id for e in selected})!=len(f['evidence_ids']) or len(selected)!=len(f['evidence_ids']):raise ValueError('unique_original_weather_evidence_required')
 selected.sort(key=lambda e:f['evidence_ids'].index(e.id));expected=next(x for x in estimate(f['contract'],selected,cutoff=cutoff) if x['model_id']==f['model_id'])
 if any(f.get(k)!=v for k,v in expected.items()):raise ValueError('weather_model_replay_mismatch')
 m=MarketSnapshot.model_validate(f['market']);b=OrderBookSnapshot.model_validate(f['book'])
 if m.exchange!=b.exchange or b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or digest(b.model_dump(mode='json'))!=f['book_sha256'] or not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('original_native_weather_quote_binding_required')
 if f['market_probability'] is not None or f['market_expected_payout']!=(b.bids[0].price+b.asks[0].price)/2:raise ValueError('weather_market_baseline_mismatch')
 return {'verified':True,'forecast_id':f.get('id'),'research_only':True,'trading_authority':False,'certification_authority':False}
