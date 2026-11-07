"""Exact-station Chengdu/AWC expansion with independently falsifiable weather models.

Both challengers use the same station data: no independent confirmation claim.
The target is conditional on ordinary AWC availability/correction semantics.
"""
import asyncio
import hashlib
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, stdev
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase14.weather import rounded_celsius
from neraium_poly.research.phase24 import weather as base
from neraium_poly.research.phase24.weather import (
    PATH,
    RULE_TEMPLATE,
    _final_weather,
    _observations,
    at,
)

STATIONS={**base.STATIONS,'ZUUU':{'city':'Chengdu','name':'Chengdu Shuangliu International Airport','timezone':'Asia/Shanghai'}}
MODELS=('metar-recency-kernel-v25.1','metar-diurnal-gaussian-v25.1')


def definitions():
    sha=hashlib.sha256(Path(__file__).read_bytes()+Path(base.__file__).read_bytes()).hexdigest()
    return [{'model_id':m,'model_version':m,'model_sha256':digest([sha,m]),'feature_version':'complete-local-day-diurnal-rise-v25',
       'domain':'weather','hypothesis':hypothesis,'input_requirements':['exact routine-AWC source/rules/station','21 complete local days','complete elapsed local-day hours'],
       'performance_criteria':['prospective verified-station Brier/log loss','chronological held-out calibration','same-cutoff market expected-payout comparison only with compatible conditioning'],
       'risk_assumptions':'Uncalibrated stationarity/kernel/normality assumptions, uncertainty[0,1], no execution authority',
       'failure_conditions':['regime/season change','incomplete station hours','AWC fallback/correction','Gaussian residual misspecification'],
       'source_independence':'Both models share AWC observations and are not independent evidence sources',
       'research_only':True,'trading_authority':False,'certification_authority':False}
       for m,hypothesis in zip(MODELS,['Recent and current-temperature-matched diurnal analog frequencies with Jeffreys smoothing',
          'Normal distribution fitted to authentic remaining-diurnal-high samples, not deterministic weather forecast'])]


def supports(market,*,cutoff):
    try:
        now=at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if isinstance(market,MarketSnapshot) else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or max(m.timestamp,m.available_at)>now or m.outcome not in {'Yes','No'} or not m.end_time or m.end_time<=now):
            raise ValueError('causal_active_weather_market_required')
        q=re.fullmatch(r'Will the highest temperature in (Chongqing|Qingdao|Chengdu) be (-?\d{1,2})°C(?: or (higher|below))? on ([A-Z][a-z]+ \d{1,2})\?',m.question)
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
    if current_max is not None and tail=='higher' and rounded_celsius(current_max)>=threshold:
        raise ValueError('weather_threshold_already_attained_not_prospective')
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
    # Frozen hyperparameters: three Celsius degrees matching scale and 0.985/day decay.
    weights=[]
    for i,(_day,rows) in enumerate(training):
        distance=0.
        if current:
            hourly={at(r['at']).astimezone(zone).hour:r['temperature'] for r in rows}
            distance=abs(last['temperature']-hourly[hour])
        weights.append(math.exp(-distance/3)*.985**(len(training)-i-1))
    samples=[max(current_max,x) if current_max is not None else x for x in analog]
    weighted_hits=sum(w for w,x in zip(weights,samples) if matches(x));weight=sum(weights)
    effective=weight**2/sum(w*w for w in weights)
    if effective<5 or len(set(samples))<3:raise ValueError('weather_effective_sample_or_variation_insufficient')
    kernel=(weighted_hits+.5)/(weight+1)
    mu=mean(samples);sigma=stdev(samples)
    if sigma<=0:raise ValueError('weather_nonzero_observed_distribution_required')
    def cdf(value):
        # CDF P(max(observed high, X) < value): retain the physical lower bound
        # and its point mass rather than assigning probability below a known high.
        if current_max is not None and value<=current_max:return 0.
        return .5*(1+math.erf((value-mu)/(sigma*math.sqrt(2))))
    gaussian=(1-cdf(threshold-.5)) if tail=='higher' else cdf(threshold+.5) if tail=='below' else cdf(threshold+.5)-cdf(threshold-.5)
    results=[]
    for definition,yes in zip(definitions(),(kernel,gaussian)):
        p=yes if contract['selected_outcome']=='Yes' else 1-yes
        results.append({**definition,'domain':'weather','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
            'probability':p,'probability_semantics':'binary_event_probability','lower_probability':0.,'upper_probability':1.,
            'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_model_uncertainty_not_confidence_interval'},
            'evidence_cutoff':cutoff.isoformat(),'event_end_time':contract['period_end'],'rules_sha256':contract['rules_sha256'],
            'evidence_ids':[e.id if hasattr(e,'id') else e['id'] for e in evidence],'source_lineages':['NOAA/AWC:'+contract['station']],
            'training_days':[day for day,_rows in training],'training_observations':len(training),'effective_analog_sample_size':effective,
            'dataset_sha256':digest(observations),'contract':contract,'independent_of_polymarket':True,'calibration_status':'unvalidated_research',
            'conditioning':'routine AWC availability and no material future correction/fallback','unconditional_contract_probability':False,
            'distribution_assumptions':{'analog_match_scale_celsius':3.,'daily_decay':.985,'sample_mean':mu,'sample_sd':sigma},
            'limitations':['Unvalidated seasonal stationarity and distribution assumptions','Raw history first retrieved now, not a historical vintage',
                'AWC fallback, corrections and native settlement require verified corroboration'],
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return results


async def forecast(market,book,*,clock):
    m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market);support=supports(m,cutoff=at(clock()))
    if not support['supported']:return {'forecasts':[],'evidence':[],'rejections':support['reasons']}
    evidence=()
    try:
        evidence=await base.collect(support['contract'],clock=clock);cutoff=at(clock())
        b=OrderBookSnapshot.model_validate(book.model_dump() if hasattr(book,'model_dump') else book) if book is not None else None
        if b is None or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy:
            adapter=OperationalPolymarketAdapter(clock=clock)
            try:b=await adapter.book(m.market_id,m.token_id)
            finally:await adapter.close()
            cutoff=at(clock())
        if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy:
            raise ValueError('fresh_native_two_sided_weather_book_required')
        results=await asyncio.to_thread(estimate,support['contract'],evidence,cutoff=cutoff);created=at(clock())
        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('weather_book_stale_after_model')
        for f in results:f.update(timestamp=created.isoformat(),market=m.model_dump(mode='json'),book=b.model_dump(mode='json'),
            book_id=b.id,book_sha256=digest(b.model_dump(mode='json')),market_probability=None,market_expected_payout=(b.bids[0].price+b.asks[0].price)/2)
        return {'forecasts':results,'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
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


async def verify_outcome(forecast,*,directory,clock):
    # Same exact AWC/native settlement proof protocol; source identity is in contract.
    return await base.verify_outcome(forecast,directory=directory,clock=clock)


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
