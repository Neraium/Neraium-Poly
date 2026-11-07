"""Controlled fixtures only; these are not authentic forecasts or outcomes."""

import hashlib
import json
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.finance import ORIGIN, digest
from neraium_poly.research.phase18.forecasting import daily_low_rules, forecast_event, map_event_contract
from neraium_poly.research.phase18.sources import collect_event_evidence, completed_minutes

CUTOFF = datetime(2026, 11, 7, 3, 0, 20, tzinfo=UTC)
START = datetime(2026, 11, 6, 5, tzinfo=UTC)


def market(threshold=74800, outcome='Yes', now=CUTOFF):
    return MarketSnapshot(id='controlled-market-record', timestamp=now-timedelta(seconds=1),
        available_at=now-timedelta(seconds=1), source='https://gamma-api.polymarket.com',
        market_id='controlled-market', event_id='controlled-parent', token_id='controlled-token',
        question=f'Will Bitcoin dip to ${threshold:,} on November 6?', outcome=outcome, probability=.5,
        status='active', end_time=datetime(2026,11,7,5,tzinfo=UTC), resolution_rules=daily_low_rules('Bitcoin'),
        resolution_source='https://www.binance.com/en/trade/BTC_USDT')


def artifact(cutoff=CUTOFF):
    end_ms=int(cutoff.timestamp()//60*60000)-1;start_ms=int(START.timestamp()*1000)
    rows=[]
    for i,opened in enumerate(range(start_ms,end_ms,60000)):
        close=75000+50*math.sin(i*.2);opening=75000+50*math.sin((i-1)*.2)
        rows.append([opened,str(opening),str(max(opening,close)+5),str(min(opening,close)-5),str(close),'2',opened+59999,'0',2,'0','0','0'])
    responses=[];cursor=start_ms
    for offset in range(0,len(rows),1000):
        page=rows[offset:offset+1000];raw=json.dumps(page,separators=(',',':'))
        responses.append({'url':ORIGIN+'/api/v3/klines','request':{'symbol':'BTCUSDT','interval':'1m','limit':1000,'startTime':cursor,'endTime':end_ms},
            'retrieved_at':cutoff.isoformat(),'raw_response_utf8':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest()})
        cursor=page[-1][6]+1
    payload={'kind':'binance_complete_closed_minutes','symbol':'BTCUSDT','requested_at':cutoff.isoformat(),
        'start_ms':start_ms,'end_ms':end_ms,'responses':responses,'availability_basis':'actual_retrieval_only'}
    return DomainEvidence(id='controlled-external-evidence', timestamp=cutoff,available_at=cutoff,retrieved_at=cutoff,
        source_timestamp=datetime.fromtimestamp(end_ms/1000,UTC),source=ORIGIN,domain='crypto',
        provider='Binance public market data',source_id='CONTROLLED',content_sha256=digest(payload),payload=payload,
        independent_of_polymarket=True,qualification='qualified_research',missingness=('heldout_calibration',))


def rehash(e,payload):return e.model_copy(update={'payload':payload,'content_sha256':digest(payload)})


def test_exact_daily_mapping_and_independent_conditional_probability_reproducible():
    c=map_event_contract(market(),now=CUTOFF);e=artifact();r=forecast_event(c,(e,),cutoff=CUTOFF)
    assert c.compatible and not c.review_required and c.contract_type=='binance_daily_low_barrier'
    assert r['status']=='research_estimate' and 0<r['probability']<1
    assert r==forecast_event(c,(e,),cutoff=CUTOFF)
    assert r['training_returns']==720 and r['elapsed_window_candles']==1320
    assert r['lower_probability']==0 and r['upper_probability']==1
    assert r['calibration_status']=='unvalidated_research' and r['brier'] is None
    assert r['independent_of_polymarket'] is True and r['trading_authority'] is False
    assert r['certification_authority'] is False


def test_yes_no_complement_and_threshold_monotonicity():
    e=artifact();result=[]
    for threshold in [74700,74800]:
        c=map_event_contract(market(threshold),now=CUTOFF);result.append(forecast_event(c,(e,),cutoff=CUTOFF)['probability'])
    assert result[1]>result[0]
    no=map_event_contract(market(74800,'No'),now=CUTOFF)
    assert abs(forecast_event(no,(e,),cutoff=CUTOFF)['probability']+result[1]-1)<1e-12


def test_polymarket_price_is_not_a_predictive_input():
    e=artifact();a=map_event_contract(market(),now=CUTOFF)
    m=market().model_copy(update={'probability':.999})
    b=map_event_contract(m,now=CUTOFF)
    assert forecast_event(a,(e,),cutoff=CUTOFF)['probability']==forecast_event(b,(e,),cutoff=CUTOFF)['probability']


def test_unknown_current_minute_is_included_from_last_close_not_cutoff():
    c=map_event_contract(market(),now=CUTOFF);e=artifact();r=forecast_event(c,(e,),cutoff=CUTOFF)
    last=completed_minutes(e,cutoff=CUTOFF,symbol='BTCUSDT')[-1]
    horizon=(datetime(2026,11,7,5,tzinfo=UTC).timestamp()*1000-last['close_ms'])/60000
    z=math.log(74800/r['reference_price'])/(r['measured_sigma_per_sqrt_minute']*math.sqrt(horizon))
    assert abs(r['probability']-math.erfc(-z/math.sqrt(2)))<1e-15
    assert r['reference_age_seconds']>20
    later=forecast_event(c,(e,),cutoff=CUTOFF+timedelta(seconds=20))
    assert later['probability']==r['probability']  # Same information, same conditioning time.
    assert later['forecast_horizon_seconds']<r['forecast_horizon_seconds']


@pytest.mark.parametrize('field,value',[
    ('resolution_source','https://other-exchange.invalid/BTC_USDT'),
    ('resolution_rules',daily_low_rules('Bitcoin')+' Altered.'),
    ('question','Will Bitcoin reach $74,800 on November 6?'),
    ('end_time',datetime(2026,11,7,6,tzinfo=UTC)),
    ('outcome','UP'),('source','https://unqualified.invalid'),('status','resolved')])
def test_ambiguous_rule_source_time_or_outcome_mapping_quarantines(field,value):
    c=map_event_contract(market().model_copy(update={field:value}),now=CUTOFF)
    assert c.review_required and not c.compatible
    assert forecast_event(c,(artifact(),),cutoff=CUTOFF)['probability'] is None


def test_already_observed_low_is_not_a_prospective_forecast_or_verified_settlement():
    c=map_event_contract(market(75000),now=CUTOFF);r=forecast_event(c,(artifact(),),cutoff=CUTOFF)
    assert r['probability'] is None and 'already_observed' in r['reasons'][0]


def test_contract_parameter_tampering_and_future_evidence_reject():
    c=map_event_contract(market(),now=CUTOFF);params=deepcopy(c.parameters);params['threshold']=74000
    r=forecast_event(c.model_copy(update={'parameters':params}),(artifact(),),cutoff=CUTOFF)
    assert r['probability'] is None and 'binding' in r['reasons'][0]
    r=forecast_event(c,(artifact(),),cutoff=CUTOFF-timedelta(seconds=1))
    assert r['probability'] is None


@pytest.mark.parametrize('change', ['hash','symbol','gap','duplicate','forming','ohlc','reference','request_future','availability'])
def test_raw_source_corruption_incomplete_or_future_inputs_fail_closed(change):
    e=artifact();p=deepcopy(e.payload);item=p['responses'][0]
    if change=='hash':item['raw_response_sha256']='0'*64
    elif change=='symbol':p['symbol']='ETHUSDT'
    elif change=='reference':item['url']='https://other.invalid/api/v3/klines'
    elif change=='request_future':p['end_ms']+=60000
    elif change=='availability':p['availability_basis']='backdated_event_time'
    else:
        rows=json.loads(item['raw_response_utf8'])
        if change=='gap':rows.pop(2)
        elif change=='duplicate':rows.insert(2,rows[1])
        elif change=='forming':rows[0][6]=int(CUTOFF.timestamp()*1000)
        elif change=='ohlc':rows[0][2]='-1'
        item['raw_response_utf8']=json.dumps(rows);item['raw_response_sha256']=hashlib.sha256(item['raw_response_utf8'].encode()).hexdigest()
    with pytest.raises(ValueError):completed_minutes(rehash(e,p),cutoff=CUTOFF,symbol='BTCUSDT')


def test_zero_volatility_missing_coverage_and_stale_reference_withheld():
    e=artifact();p=deepcopy(e.payload)
    for item in p['responses']:
        rows=json.loads(item['raw_response_utf8'])
        for row in rows:row[1:5]=['75000','75001','74999','75000']
        item['raw_response_utf8']=json.dumps(rows);item['raw_response_sha256']=hashlib.sha256(item['raw_response_utf8'].encode()).hexdigest()
    c=map_event_contract(market(),now=CUTOFF)
    assert 'variation' in forecast_event(c,(rehash(e,p),),cutoff=CUTOFF)['reasons'][0]
    assert forecast_event(c,(artifact(),),cutoff=CUTOFF+timedelta(minutes=3))['probability'] is None


def test_weather_and_economic_context_never_become_unsupported_numeric_probabilities():
    c=map_event_contract(market(),now=CUTOFF)
    for domain in ['weather','economics','politics','science']:
        d=c.model_copy(update={'domain':domain})
        assert forecast_event(d,(artifact(),),cutoff=CUTOFF)['probability'] is None


async def test_source_collection_is_bounded_and_uses_actual_retrieval_availability(monkeypatch):
    from neraium_poly.research.phase18 import sources
    monkeypatch.setattr(sources,"_now",lambda:CUTOFF+timedelta(seconds=1))
    e=artifact();c=map_event_contract(market(),now=CUTOFF);calls=[]
    def handler(request):
        calls.append(request)
        start=int(request.url.params['startTime'])
        item=next(v for v in e.payload['responses'] if v['request']['startTime']==start)
        return httpx.Response(200,content=item['raw_response_utf8'].encode())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence=await collect_event_evidence(c,now=CUTOFF,client=client)
    assert len(calls)==2 and all(r.method=='GET' and r.url.host=='data-api.binance.vision' for r in calls)
    assert evidence[0].retrieved_at==CUTOFF+timedelta(seconds=1) and evidence[0].available_at==evidence[0].retrieved_at
    assert evidence[0].qualification=='qualified_research'
    # Old event data retrieved today is not available at an old prediction cutoff.
    assert forecast_event(c,evidence,cutoff=CUTOFF)['probability'] is None


async def test_access_rejection_has_no_proxy_source_or_retry_fallback():
    c=map_event_contract(market(),now=CUTOFF);calls=[]
    def handler(request):calls.append(request);return httpx.Response(451)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):await collect_event_evidence(c,now=CUTOFF,client=client)
    assert len(calls)==1


def test_existing_noon_close_ambiguity_is_not_silently_reviewed():
    from test_phase14_finance import NOW
    from test_phase14_finance import market as terminal_market
    c=map_event_contract(terminal_market(),now=NOW)
    assert c.contract_type=='binance_minute_terminal_close_above' and c.review_required
    assert forecast_event(c,(),cutoff=NOW)['probability'] is None


def test_december31_date_infers_previous_year_from_january1_end():
    now=datetime(2026,12,31,23,tzinfo=UTC)
    m=market(now=now).model_copy(update={'question':'Will Bitcoin dip to $74,800 on December 31?',
        'end_time':datetime(2027,1,1,5,tzinfo=UTC)})
    c=map_event_contract(m,now=now)
    assert c.compatible and c.parameters['period_start_utc']=='2026-12-31T05:00:00+00:00'


async def test_historical_resolution_fetch_bounds_exact_closed_window_and_preserves_availability(monkeypatch):
    from neraium_poly.research.phase18 import sources
    end=datetime(2026,11,7,5,tzinfo=UTC);retrieval=end+timedelta(days=5)
    monkeypatch.setattr(sources,'_now',lambda:retrieval)
    e=artifact(end);c=map_event_contract(market(),now=CUTOFF);calls=[]
    def handler(request):
        calls.append(request);start=int(request.url.params['startTime'])
        item=next(v for v in e.payload['responses'] if v['request']['startTime']==start)
        return httpx.Response(200,content=item['raw_response_utf8'].encode())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence=await collect_event_evidence(c,now=retrieval,client=client,resolution_window=True)
    assert len(calls)==2 and evidence[0].available_at==retrieval
    rows=completed_minutes(evidence[0],cutoff=retrieval,symbol='BTCUSDT',require_fresh=False)
    assert rows[-1]['close_ms']==int(end.timestamp()*1000)-1
    with pytest.raises(ValueError):completed_minutes(evidence[0],cutoff=retrieval,symbol='BTCUSDT')
    assert forecast_event(c,evidence,cutoff=retrieval)['probability'] is None
