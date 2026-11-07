"""Prospective exact-station METAR temperature distributions; no trading authority."""
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase14.weather import _temperature, rounded_celsius

ORIGIN="https://aviationweather.gov"
PATH="/api/data/metar"
STATIONS={"ZUCK":{"city":"Chongqing","name":"Chongqing Jiangbei International Airport","timezone":"Asia/Shanghai"},
          "ZSQD":{"city":"Qingdao","name":"Qingdao Jiaodong International Airport","timezone":"Asia/Shanghai"}}
MODELS=("metar-diurnal-analog-v24.1","metar-recent-climatology-v24.1")
RULE_TEMPLATE="This market will resolve to the temperature range that contains the highest temperature reported at {station_name} ({station}) on {rule_day}.\n\nThe qualifying value is the highest temperature reported in the hourly temperature remark of any routine (METAR) observation for {station_name} ({station}) on that date, in tenths of a degree Celsius as reported. A report whose line begins with SPECI is a special observation and does not count. Every other report is routine, including one issued off the nominal hour and one that carries no METAR or SPECI label.\n\nFor How to Read the METAR Report, see: https://polymarket-upload.s3.us-east-2.amazonaws.com/market_products/Weather/How+to+Read+the+METAR+Report.pdf\n\nThe hourly temperature remark is the group beginning with the letter T followed by exactly eight digits. After the T, one digit for sign (0 positive, 1 negative) and three for tenths of a degree Celsius give the temperature; the following four are the dew point and are not used. T01390133 is 13.9°C; T10171022 is −1.7°C.\n\nIf a routine observation does not carry the hourly temperature remark, the temperature group in the body of that observation governs for that observation, in whole degrees Celsius as reported. It appears as temperature and dew point separated by a slash, with M marking a negative value: 18/12 is 18°C; M11/M17 is −11°C. An observation that reports no temperature in either place is disregarded.\n\nEach market in this event states its range in whole degrees Celsius. The qualifying value is rounded to the nearest whole degree, with a value ending in exactly half rounded up to the next higher whole degree, and that whole Celsius value determines which range contains it. For example, 13.9°C counts as 14°C; 17.4°C counts as 17°C; 16.5°C counts as 17°C; −1.7°C counts as −2°C; −8.5°C counts as −8°C.\n\nAn observation counts if its time stamp, converted to the station's local time (including any daylight-saving shift in effect), falls on the observation date.\n\nThis market will resolve at the issuance of the first METAR observation for the station on the day following the observation date or by 11:59 PM ET on the day following the observation date, whichever comes first. Resolution is determined from the observations the resolution source shows for the observation date.\n\nIn the event that the Aviation Weather Center has published no routine observation reporting a temperature for the observation date by 11:59 PM ET on the day following the observation date, the Weather Underground Daily Observations table will be used as the resolution source. In the event that neither source has published data sufficient to determine a temperature for the observation date by 11:59 PM ET on the day following the observation date, this market will resolve to the lowest bracket.\n\nThe report the resolution source shows for a given observation time is the one that counts, whether or not it is marked as a correction (COR). Changes to observations within this market's timeframe will be considered until the first datapoint for the following date has been published, after which any alterations will not be considered. Where the first routine observation for the following date is published before that deadline, resolution is determined from a read taken after it. Where it is not, resolution is determined from a read taken at that deadline.\n\nIn the case that the Resolution Source publishes data, sufficient to settle a Market, that is clearly erroneous and the result of technical or operational error, or of unauthorized interference with the Resolution Source or its data, the Market may remain open for a period of up to seven (7) calendar days (ET) from the time of the original release, in anticipation of a correction by the Resolution Source. If the Resolution Source publishes a corrected value within that period, that value will be eligible for resolution. If no corrected value is published within that period, Polymarket will issue a Clarification to determine whether the originally published value may be eligible for resolution, or whether other action is required to preserve the orderly functioning of the Market.\n\nThe resolution source for this market will be the routine observations for {station_name} ({station}) published here:\n{source_url}"
_CACHE={}


def at(value):
    t=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if t.tzinfo is None:raise ValueError('aware_weather_cutoff_required')
    return t.astimezone(UTC)


def definitions():
    sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return [{'model_id':m,'model_version':m,'model_sha256':digest([sha,m]),
             'feature_version':'complete-routine-METAR-local-day-and-diurnal-residual-v1',
             'hypothesis':h,'input_requirements':['exact audited routine-METAR daily-high rule','21 complete station-local days','qualified raw AWC observations'],
             'performance_criteria':['verified-station-outcome Brier/log-loss','chronological calibration vs same-time market baseline'],
             'risk_assumptions':'Uncalibrated research; full [0,1] model uncertainty; no execution',
             'failure_conditions':['weather-regime shifts','seasonal drift','future corrections','missing routine reports'],
             'source_independence':'Both models use AWC and are not independent confirmations',
             'research_only':True,'trading_authority':False,'certification_authority':False}
            for m,h in zip(MODELS,['Conditional distribution of remaining diurnal rise from complete recent station days',
                                   'Recent complete local-day high empirical frequency control'])]


def supports(market,*,cutoff):
    try:
        now=at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if isinstance(market,MarketSnapshot) else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or max(m.timestamp,m.available_at)>now or m.outcome not in {'Yes','No'} or not m.end_time or m.end_time<=now):
            raise ValueError('causal_active_weather_market_required')
        q=re.fullmatch(r'Will the highest temperature in (Chongqing|Qingdao) be (-?\d{1,2})°C(?: or (higher|below))? on ([A-Z][a-z]+ \d{1,2})\?',m.question)
        if not q:raise ValueError('unsupported_weather_question')
        city,k,tail,date=q.groups();u=urlsplit(m.resolution_source);params=parse_qs(u.query)
        if u.scheme!='https' or u.netloc!='aviationweather.gov' or u.path!=PATH or set(params)!={'ids','format','date','hours'}:
            raise ValueError('exact_AWC_station_resolution_source_required')
        station=params['ids'][0];spec=STATIONS.get(station)
        if not spec or spec['city']!=city or params['format']!=['raw'] or params['hours']!=['30']:
            raise ValueError('reviewed_station_and_resolution_window_required')
        source_end=at(params['date'][0]);zone=ZoneInfo(spec['timezone'])
        day=(source_end.astimezone(zone)-timedelta(days=1)).date()
        start=datetime.combine(day,datetime.min.time(),zone).astimezone(UTC);end=start+timedelta(days=1)
        if source_end!=end+timedelta(hours=3) or datetime.strptime(f'{day.year} {date}','%Y %B %d').date()!=day:
            raise ValueError('exact_station_local_observation_date_required')
        if not start-timedelta(days=1)<=now<end or not -80<=int(k)<=60:
            raise ValueError('near_term_unresolved_weather_window_required')
        expected=RULE_TEMPLATE.format(station_name=spec['name'],station=station,rule_day=day.strftime("%-d %b '%y"),source_url=m.resolution_source)
        if m.resolution_rules!=expected:raise ValueError('weather_rule_template_changed_or_ambiguous')
        contract={'station':station,**spec,'day':day.isoformat(),'period_start':start.isoformat(),'period_end':end.isoformat(),
                  'threshold':int(k),'tail':tail,'selected_outcome':m.outcome,'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
                  'source_url':m.resolution_source,'market':m.model_dump(mode='json')}
        return {'supported':True,'reasons':[],'contract':contract}
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {'supported':False,'reasons':[str(error)[:160]],'contract':None}


async def _fetch(station,end,clock):
    params={'ids':station,'format':'json','date':at(end).strftime('%Y-%m-%dT%H:%M:%SZ'),'hours':360}
    async with httpx.AsyncClient(timeout=10,follow_redirects=False,headers={'User-Agent':'Neraium-Poly bounded public research/0.24'}) as client:
        response=await client.get(ORIGIN+PATH,params=params);response.raise_for_status();raw=response.content
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_AWC_response_required')
    body=raw.decode();rows=json.loads(body);received=at(clock())
    if not isinstance(rows,list) or not 1<=len(rows)<=400:raise ValueError('bounded_AWC_observations_required')
    payload={'request_url':str(response.url),'request_parameters':params,'raw_response_utf8':body,
             'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'historical_availability':'first observed retrieval only; not a historical vintage claim'}
    return DomainEvidence(id=digest(['AWC-station-history',payload,received.isoformat()]),timestamp=received,available_at=received,
        source=ORIGIN+PATH,domain='weather',provider='NOAA/NWS Aviation Weather Center',source_id=station,
        retrieved_at=received,source_timestamp=max(datetime.fromtimestamp(x['obsTime'],UTC) for x in rows),
        content_sha256=digest(payload),payload=payload,independent_of_polymarket=True,qualification='qualified_research')


async def collect(contract,*,clock):
    now=at(clock());station=contract['station'];cached=_CACHE.get(station)
    if cached and 0<=(now-cached[-1].available_at).total_seconds()<300:return cached
    result=(await _fetch(station,now,clock),await _fetch(station,now-timedelta(days=14),clock))
    _CACHE[station]=result
    return result


def _observations(contract,evidence,cutoff):
    station=contract['station'];by_time={}
    if len(evidence)!=2:raise ValueError('two_bounded_AWC_chunks_required')
    for value in evidence:
        e=DomainEvidence.model_validate(value.model_dump() if hasattr(value,'model_dump') else value);p=e.payload
        if (e.domain!='weather' or e.provider!='NOAA/NWS Aviation Weather Center' or e.source_id!=station
            or e.source!=ORIGIN+PATH or not e.independent_of_polymarket or e.qualification!='qualified_research'
            or max(e.timestamp,e.available_at,e.retrieved_at)>cutoff or digest(p)!=e.content_sha256
            or hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest()!=p['raw_response_sha256']):
            raise ValueError('causal_exact_station_AWC_raw_provenance_required')
        query=p['request_parameters'];u=urlsplit(p['request_url'])
        if (u.scheme!='https' or u.netloc!='aviationweather.gov' or u.path!=PATH or query['ids']!=station
            or query['format']!='json' or query['hours']!=360 or at(query['date'])>e.retrieved_at
            or parse_qs(u.query)!={key:[str(value)] for key,value in query.items()}):
            raise ValueError('AWC_query_identity_mismatch')
        rows=json.loads(p['raw_response_utf8'])
        if not isinstance(rows,list) or not 1<=len(rows)<=400:raise ValueError('bounded_AWC_chunk_required')
        if e.source_timestamp!=max(datetime.fromtimestamp(r['obsTime'],UTC) for r in rows):raise ValueError('AWC_source_timestamp_mismatch')
        for r in rows:
            t=datetime.fromtimestamp(r['obsTime'],UTC);received=at(r['receiptTime']);raw=r['rawOb'].strip()
            if r['icaoId']!=station or max(t,received)>e.available_at or not at(query['date'])-timedelta(hours=360)<=t<=at(query['date']):raise ValueError('noncausal_or_mapped_station_observation')
            if raw.startswith('SPECI'):continue
            if not re.match(r'^(?:METAR\s+)?'+station+r'\s',raw):raise ValueError('raw_METAR_station_mismatch')
            temp=float(_temperature(raw)[0])
            if not -80<=temp<=60:raise ValueError('implausible_METAR_temperature')
            item={'at':t.isoformat(),'temperature':temp,'received_at':received.isoformat(),'raw':raw}
            prior=by_time.get(t)
            if prior and prior['received_at']==item['received_at'] and prior['raw']!=raw:raise ValueError('conflicting_routine_METAR_versions')
            if not prior or at(prior['received_at'])<received:by_time[t]=item
    if not by_time:raise ValueError('routine_METAR_history_empty')
    latest=max(by_time)
    if (cutoff-latest).total_seconds()>90*60:raise ValueError('current_station_observation_stale')
    return [by_time[t] for t in sorted(by_time)]


def estimate(contract,evidence,*,cutoff):
    cutoff=at(cutoff);m=MarketSnapshot.model_validate(contract['market']);mapped=supports(m,cutoff=cutoff)
    if not mapped['supported'] or mapped['contract']!=contract:raise ValueError('exact_weather_contract_replay_required')
    observations=_observations(contract,evidence,cutoff);zone=ZoneInfo(contract['timezone']);days=defaultdict(list)
    for r in observations:days[at(r['at']).astimezone(zone).date().isoformat()].append(r)
    training=[]
    for day,rows in sorted(days.items()):
        if day>=contract['day']:continue
        hours={at(r['at']).astimezone(zone).hour for r in rows}
        if hours!=set(range(24)):continue
        training.append((day,rows))
    if len(training)<21:raise ValueError('21_complete_station_local_days_required')
    if len({max(x['temperature'] for x in rows) for _,rows in training})<3:raise ValueError('station_variation_required')
    current=days.get(contract['day'],[])
    current_max=max((r['temperature'] for r in current),default=None)
    threshold=contract['threshold'];tail=contract['tail']
    if current_max is not None and tail!='higher' and rounded_celsius(current_max)>threshold:
        raise ValueError('target_bin_already_exceeded_by_observed_station_high')
    highs=[max(r['temperature'] for r in rows) for _,rows in training]
    analog=[]
    if current:
        last=current[-1];hour=at(last['at']).astimezone(zone).hour
        if {at(r['at']).astimezone(zone).hour for r in current}!=set(range(hour+1)):
            raise ValueError('complete_elapsed_station_hour_coverage_required')
        for _,rows in training:
            hourly={at(r['at']).astimezone(zone).hour:r['temperature'] for r in rows}
            future=max(r['temperature'] for r in rows if at(r['at']).astimezone(zone).hour>=hour)
            analog.append(max(current_max,last['temperature']+future-hourly[hour]))
    else:analog=highs[:]
    def matches(x):
        rounded=rounded_celsius(x)
        return rounded>=threshold if tail=='higher' else rounded<=threshold if tail=='below' else rounded==threshold
    results=[]
    for definition,samples in zip(definitions(),(analog,highs)):
        if current_max is not None:samples=[max(current_max,x) for x in samples]
        hits=sum(matches(x) for x in samples);yes=(hits+.5)/(len(samples)+1)
        p=yes if contract['selected_outcome']=='Yes' else 1-yes
        results.append({**definition,'domain':'weather','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
            'probability':p,'probability_semantics':'binary_event_probability','lower_probability':0.,'upper_probability':1.,
            'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_model_uncertainty_not_confidence_interval'},
            'evidence_cutoff':cutoff.isoformat(),'event_end_time':contract['period_end'],'rules_sha256':contract['rules_sha256'],
            'evidence_ids':[e.id if hasattr(e,'id') else e['id'] for e in evidence],'source_lineages':['NOAA/AWC:'+contract['station']],
            'training_days':[day for day,_ in training],'training_observations':len(training),'empirical_hits':hits,
            'empirical_sample_size':len(samples),'prior':'Jeffreys Beta(0.5,0.5), not artificial temperature noise',
            'dataset_sha256':digest(observations),'contract':contract,'independent_of_polymarket':True,
            'calibration_status':'unvalidated_research','brier':None,'log_loss':None,
            'conditioning':'routine AWC availability and no material future correction/fallback',
            'unconditional_contract_probability':False,'market_comparison_status':'conditional_station_probability_not_unconditional_token_payout',
            'limitations':['Recent climate and diurnal stationarity are testable assumptions, not validated skill',
                'Historical observations retrieved now; no pre-retrieval historical availability asserted',
                'Fallbacks, corrections and settlement require independent native proof; no automatic resolution'],
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return results


async def forecast(market,book,*,clock):
    now=at(clock());m=MarketSnapshot.model_validate(market);b=OrderBookSnapshot.model_validate(book);mapped=supports(m,cutoff=now)
    if not mapped['supported']:return {'forecasts':[],'evidence':[],'rejections':mapped['reasons']}
    evidence=()
    try:
        if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or not assess_book(b,now,max_spread=.05,expected_token=m.token_id).healthy:
            raise ValueError('fresh_native_two_sided_weather_book_required')
        evidence=await collect(mapped['contract'],clock=clock);cutoff=at(clock());results=estimate(mapped['contract'],evidence,cutoff=cutoff);created=at(clock())
        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('weather_book_stale_after_source_collection')
        rows=[{**r,'timestamp':created.isoformat(),'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),
               'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'market_probability':None,'market_expected_payout':(b.bids[0].price+b.asks[0].price)/2} for r in results]
        return {'forecasts':rows,'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
    except (ValueError,TypeError,KeyError,httpx.HTTPError) as error:
        return {'forecasts':[],'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[str(error)[:180]]}


def replay(forecast,evidence,*,as_of):
    f=forecast;now=at(as_of);created=at(f['timestamp']);cutoff=at(f['evidence_cutoff'])
    if not cutoff<=created<=now:raise ValueError('weather_forecast_temporal_binding_required')
    selected=[DomainEvidence.model_validate(x) for x in evidence if x['id'] in f['evidence_ids']]
    selected.sort(key=lambda x:f['evidence_ids'].index(x.id))
    result=next(x for x in estimate(f['contract'],selected,cutoff=cutoff) if x['model_id']==f['model_id'])
    if any(f.get(k)!=v for k,v in result.items()):raise ValueError('weather_model_replay_mismatch')
    m=MarketSnapshot.model_validate(f['market']);b=OrderBookSnapshot.model_validate(f['book'])
    if b.source not in PUBLIC_BOOK_SOURCES or b.exchange!=m.exchange or digest(b.model_dump(mode='json'))!=f['book_sha256'] or b.market_id!=m.market_id or not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:
        raise ValueError('weather_original_executable_quote_binding_required')
    if f['market_probability'] is not None or f['market_expected_payout']!=(b.bids[0].price+b.asks[0].price)/2:raise ValueError('weather_market_baseline_mismatch')
    return {'verified':True,'forecast_id':f.get('id'),'research_only':True,'trading_authority':False}



def _final_weather(c,raw,now):
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_final_weather_source_required')
    end=at(c['period_end']);observations=json.loads(raw);zone=ZoneInfo(c['timezone']);dayrows=[];following=[]
    for r in observations:
        t=datetime.fromtimestamp(r['obsTime'],UTC);receipt=at(r['receiptTime'])
        if r['icaoId']!=c['station'] or max(t,receipt)>now:raise ValueError('weather_outcome_station_time_mismatch')
        if r['rawOb'].startswith('SPECI'):continue
        if not re.match(r'^(?:METAR\s+)?'+c['station']+r'\s',r['rawOb']):raise ValueError('raw_final_METAR_station_mismatch')
        if t.astimezone(zone).date().isoformat()==c['day']:dayrows.append(r)
        elif t>=end:following.append(r)
    if not dayrows or not following or {datetime.fromtimestamp(r['obsTime'],zone).hour for r in dayrows}!=set(range(24)):
        return {'verified':False,'reason':'complete_routine_day_and_first_following_report_required'}
    freeze=min(at(r['receiptTime']) for r in following)
    if any(at(r['receiptTime'])>freeze for r in dayrows):return {'verified':False,'reason':'post_freeze_corrections_ambiguous'}
    high=max(float(_temperature(r['rawOb'])[0]) for r in dayrows);value=rounded_celsius(high);k=c['threshold']
    yes=int(value>=k if c['tail']=='higher' else value<=k if c['tail']=='below' else value==k);expected=yes if c['selected_outcome']=='Yes' else 1-yes
    return {'verified':True,'expected':expected,'freeze':freeze,'end':end,'resolution_value':value}


async def verify_outcome(forecast,*,directory,clock):
    # No price-derived labels or fallback to a different station/source.
    from neraium_poly.research.phase12.contracts import SettlementProofReference
    from neraium_poly.research.phase12.outcome_collector import (
        acquire_verified_outcome,
        verify_collected_outcome,
    )
    f=forecast;c=f['contract'];now=at(clock());end=at(c['period_end'])
    if now<end+timedelta(hours=3):return {'verified':False,'reason':'weather_full_reference_and_next_day_freeze_pending'}
    # Historical AWC endpoint must be sampled after the contractual first following-day report.
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        params={'ids':c['station'],'format':'json','date':at(parse_qs(urlsplit(c['source_url']).query)['date'][0]).strftime('%Y-%m-%dT%H:%M:%SZ'),'hours':30}
        response=await client.get(ORIGIN+PATH,params=params);response.raise_for_status();raw=response.content
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_weather_final_source_required')
    observed=at(clock());final=_final_weather(c,raw,observed)
    if not final['verified']:return final
    expected,freeze,end,value=(final[k] for k in ['expected','freeze','end','resolution_value'])
    m=MarketSnapshot.model_validate(f['market']);ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],
        timestamp=at(f['timestamp']),evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    directory=Path(directory);location=directory/(now.strftime('%Y%m%dT%H%M%S%fZ')+'-'+f['id'][:12])
    proof=await acquire_verified_outcome(ref,m,location,clock=clock)
    if proof is None or not verify_collected_outcome(proof,m,ref,directory):return {'verified':False,'reason':'native_finalized_weather_proof_pending'}
    if proof.payout!=expected or proof.settled_at<max(end,freeze):return {'verified':False,'reason':'native_weather_outcome_or_freeze_mismatch'}
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'outcome':expected,'resolved_at':proof.settled_at.isoformat(),
            'available_at':at(clock()).isoformat(),'proof':proof.model_dump(mode='json'),
            'evidence':[{'provider':'NOAA/AWC','request_url':str(response.url),'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'retrieved_at':observed.isoformat()}],
            'resolution_value':value,'trading_authority':False,'certification_authority':False}


def replay_outcome(result,study,forecast,*,evidence_root,as_of):
    from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
    from neraium_poly.research.phase12.outcome_collector import verify_collected_outcome
    now=at(as_of);f=forecast
    if result.get('forecast_id')!=f['id'] or result.get('event_id')!=f['event_id'] or not at(result['available_at'])<=now:
        raise ValueError('weather_outcome_original_identity_or_availability_mismatch')
    if sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study['forecasts'])!=1:
        raise ValueError('immutable_weather_forecast_membership_required')
    if not at(f['timestamp'])<=at(study['available_at'])<=now:raise ValueError('weather_original_study_time_required')
    replay(f,study['evidence'],as_of=now)
    c=f['contract'];evidence=result['evidence']
    if len(evidence)!=1:raise ValueError('one_exact_weather_final_source_required')
    e=evidence[0];u=urlsplit(e['request_url']);q=parse_qs(u.query)
    expected={'ids':[c['station']],'format':['json'],'date':[at(parse_qs(urlsplit(c['source_url']).query)['date'][0]).strftime('%Y-%m-%dT%H:%M:%SZ')],'hours':['30']}
    raw=e['raw_response_utf8'].encode();observed=at(e['retrieved_at'])
    if (u.scheme!='https' or u.netloc!='aviationweather.gov' or u.path!=PATH or q!=expected
        or hashlib.sha256(raw).hexdigest()!=e['raw_response_sha256'] or not at(c['period_end'])<=observed<=at(result['available_at'])):
        raise ValueError('exact_weather_final_source_hash_or_time_required')
    final=_final_weather(c,raw,observed)
    if not final['verified']:raise ValueError(final['reason'])
    m=MarketSnapshot.model_validate(f['market']);proof=VerifiedEventOutcome.model_validate(result['proof'])
    ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],timestamp=at(f['timestamp']),
        evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    if (not verify_collected_outcome(proof,m,ref,Path(evidence_root)) or proof.payout!=final['expected']
        or proof.settled_at<max(final['end'],final['freeze']) or not at(f['timestamp'])<proof.settled_at<=proof.available_at<=at(result['available_at'])
        or at(result['resolved_at'])!=proof.settled_at or result['outcome']!=proof.payout):
        raise ValueError('native_and_reference_weather_finality_mismatch')
    probability=f['probability'];outcome=final['expected'];likelihood=probability if outcome else 1-probability
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
        'rules_sha256':f['rules_sha256'],'outcome':outcome,'resolved_at':proof.settled_at.isoformat(),'available_at':result['available_at'],
        'brier':(probability-outcome)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,
        'log_loss_status':'finite' if likelihood>0 else 'positive_infinity','market_brier':None,
        'score_scope':'conditional station-high descriptive score, not unconditional market superiority',
        'evidence_sha256':digest(evidence),'reviewed_dependency_group':None,'trading_authority':False,'certification_authority':False}
