"""Independent SPX direction research from authentic official-index history.

FRED SP500 is the S&P500 cash index, never a substitute for SPY, Pyth or opens.
Probabilities condition on an ordinary completed non-tied session; unknown WSJ
finality and publisher access withhold labels, not a fabricated resolution.
"""
import asyncio
import csv
import hashlib
import io
import itertools
import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import NormalDist, mean, stdev
from zoneinfo import ZoneInfo

import httpx
from websockets.asyncio.client import connect

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.data.polymarket import normalize_book, normalize_market, stable_id
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest

URL='https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500'
RESOLUTION='https://www.wsj.com/market-data/stocks'
MODELS=('spx-weekday-beta-direction-v25.1','spx-gaussian-logreturn-direction-v25.1')
CACHE=None
BOOK_RAW={}
WS='wss://ws-subscriptions-clob.polymarket.com/ws/market'
RULE='''This market will resolve to "Up" if the official S&P 500 Index closing price for S&P 500 (SPX) on {day} is higher than the official S&P 500 Index closing price for SPX on the most recent prior trading day.

This market will resolve to "Down" if the official S&P 500 Index closing price for S&P 500 (SPX) on {day} is lower than the official S&P 500 Index closing price for SPX on the most recent prior trading day.

E.g., ordinarily, a market on Monday would refer to the previous Friday for its most recent closing price, unless that Friday were a market holiday, in which case it would refer to Thursday, or the next most recent trading day.

If the two specified closing prices are exactly equal, this market will resolve 50-50. Note that all figures will be rounded to the nearest cent using standard rounding.

If SPX does not trade at all during the regular session, the market will resolve 50-50.

If either of the relevant days are shortened (for example, due to a market holiday schedule), the official closing price published by S&P 500 Index for that shortened session will still be used for resolution.

If either of the relevant days have no official closing price (for example, due to a trading halt into the market close, system issue, delisting, or other disruption), the market will use the last valid on-exchange trade price of the regular session as the effective closing price.

The resolution source for this market is the Wall Street Journal, specifically the Close values published by the WSJ under "Historical Prices".

US: https://www.wsj.com/market-data/stocks
EMEA: https://www.wsj.com/market-data/stocks/emea 
ASIA: https://www.wsj.com/market-data/stocks/asia'''


def at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('aware_external_time_required')
    return value.astimezone(UTC)


def definitions():
    sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return [{'model_id':name,'model_version':name,'model_sha256':digest([sha,name]),'domain':'finance',
        'feature_version':'sp500-current-observed-cash-closes-v1','hypothesis':hypothesis,
        'input_requirements':['official FRED SP500 cash-index raw CSV','exact SPX WSJ dailyclose rules','causal native two-sided book'],
        'performance_criteria':['prospective independently verified direction scores','event-disjoint comparison'],
        'failure_conditions':['regime change','publisher differences','holiday or no-trading session','ties','data lag'],
        'risk_assumptions':'Uncalibrated conditional research; [0,1] uncertainty; no admission',
        'source_independence':'Both models share FRED history; not independent confirmation',
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for name,hypothesis in zip(MODELS,['Historical same-weekday up frequency with Beta(1,1) prior',
                                         'Recent daily log-return Gaussian sign probability'])]


def discovery_queries():return ('S&P 500 SPX Up or Down',)


async def _discover(queries,*,clock):
    """Bounded public metadata only, never synthetic books or assumed tokens."""
    result=[];seen=set()
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        for q in queries[:3]:
            response=await client.get('https://gamma-api.polymarket.com/public-search',params={'q':q,'events_status':'active','limit_per_type':10})
            response.raise_for_status()
            if len(response.content)>4*1024**2:raise ValueError('bounded_Gamma_discovery_required')
            now=at(clock())
            for event in response.json().get('events',[])[:10]:
                for raw in event.get('markets',[])[:50]:
                    if raw.get('closed') is not False or not raw.get('active') or not raw.get('enableOrderBook') or not raw.get('acceptingOrders'):continue
                    raw={**raw,'eventId':str(event['id'])}
                    try:markets=normalize_market(raw,now)
                    except (ValueError,TypeError,KeyError):continue
                    for m in markets:
                        if m.token_id not in seen:result.append(m);seen.add(m.token_id)
    return result


async def discover(*,clock):return await _discover(discovery_queries(),clock=clock)


def supports(market,*,cutoff):
    try:
        now=at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or max(m.timestamp,m.available_at)>now or m.outcome not in {'Up','Down'} or not m.end_time or m.end_time<=now):
            raise ValueError('causal_active_SPX_direction_market_required')
        q=re.fullmatch(r'S&P 500 \(SPX\) Up or Down on ([A-Z][a-z]+ \d{1,2})\?',m.question)
        day=re.search(r'S&P 500 \(SPX\) on ([A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, 20\d{2}) is higher',m.resolution_rules)
        if not q or not day or m.resolution_source!=RESOLUTION:raise ValueError('exact_SPX_not_SPY_or_open_contract_required')
        date=datetime.strptime(day.group(1),'%A, %B %d, %Y').replace(tzinfo=ZoneInfo('America/New_York'))
        if date.strftime('%A, %B %-d, %Y')!=day.group(1) or date.strftime('%B %-d')!=q.group(1):raise ValueError('SPX_day_question_rule_mismatch')
        start=date.replace(hour=9,minute=30).astimezone(UTC);end=date.replace(hour=16).astimezone(UTC)
        if m.resolution_rules!=RULE.format(day=day.group(1)) or m.end_time!=end:raise ValueError('SPX_exact_rule_or_close_time_required')
        if not now<start<=now+timedelta(days=10) or date.weekday()>4:raise ValueError('future_weekday_session_required')
        return {'supported':True,'reasons':[],'contract':{'kind':'spx_daily_direction','symbol':'SPX','asset':'S&P 500 Index',
            'reference_source':RESOLUTION,'source_url':RESOLUTION,'target_date':date.date().isoformat(),'target_weekday':date.weekday(),
            'period_start':start.isoformat(),'period_end':end.isoformat(),'settlement_at':end.isoformat(),
            'selected_outcome':m.outcome,'market':m.model_dump(mode='json'),'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
            'conditioning':'ordinary completed strictly non-tied regular session; no halt/fallback or publisher discrepancy',
            'calendar_status':'weekday provisional; exchange holiday validity unverified, conditional forecast only'}}
    except (ValueError,TypeError,KeyError) as error:return {'supported':False,'reasons':[str(error)[:180]],'contract':None}


async def collect(*,clock):
    global CACHE
    now=at(clock())
    if CACHE is not None and 0<=(now-CACHE.available_at).total_seconds()<21600:return (CACHE,)
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        response=await client.get(URL);response.raise_for_status();raw=response.content
    received=at(clock())
    if not 0<len(raw)<=512*1024:raise ValueError('bounded_FRED_index_response_required')
    payload={'request_url':str(response.url),'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),
        'series_id':'SP500','price_definition':'S&P500 cash-index daily close','vintage_scope':'current observed snapshot, not historical availability or WSJ settlement proof'}
    CACHE=DomainEvidence(id=digest(['FRED-SP500-v25',payload,received.isoformat()]),timestamp=received,available_at=received,retrieved_at=received,
        source=URL,domain='finance',provider='Federal Reserve Bank of St. Louis FRED',source_id='SP500',payload=payload,content_sha256=digest(payload),
        qualification='qualified_research',independent_of_polymarket=True,missingness=('historical_vintages','WSJ_resolution_records','exchange_holiday_calendar'))
    return (CACHE,)


def evidence_payload(evidence,*,url,domain,provider,series,cutoff):
    if len(evidence)!=1:raise ValueError('one_exact_external_snapshot_required')
    e=DomainEvidence.model_validate(evidence[0].model_dump() if hasattr(evidence[0],'model_dump') else evidence[0]);p=e.payload;now=at(cutoff)
    if (e.source!=url or e.source_id!=series or e.domain!=domain or e.provider!=provider or not e.independent_of_polymarket
        or e.qualification!='qualified_research' or max(e.timestamp,e.available_at,e.retrieved_at)>now or p['request_url']!=url
        or digest(p)!=e.content_sha256 or hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest()!=p['raw_response_sha256']):
        raise ValueError('exact_causal_external_raw_evidence_required')
    return e,p


def estimates(contract,evidence,*,cutoff):
    now=at(cutoff);mapped=supports(contract['market'],cutoff=now)
    if not mapped['supported'] or mapped['contract']!=contract:raise ValueError('exact_SPX_contract_replay_required')
    e,p=evidence_payload(evidence,url=URL,domain='finance',provider='Federal Reserve Bank of St. Louis FRED',series='SP500',cutoff=now)
    rows=list(csv.DictReader(io.StringIO(p['raw_response_utf8'])));values=[];seen=set()
    for row in rows:
        day=datetime.strptime(row['observation_date'],'%Y-%m-%d').replace(hour=16,tzinfo=ZoneInfo('America/New_York')).astimezone(UTC)
        if day in seen or day>now:raise ValueError('unique_completed_index_days_required')
        seen.add(day)
        if row['SP500'] in {'','.','NA'}:continue
        v=float(row['SP500'])
        if not math.isfinite(v) or v<=0:raise ValueError('positive_index_close_required')
        values.append((day,v))
    if values!=sorted(values) or not 253<=len(values)<=4000 or (now-values[-1][0]).total_seconds()>7*86400:
        raise ValueError('sufficient_current_ordered_index_history_required')
    returns=[(b[0],math.log(b[1]/a[1])) for a,b in itertools.pairwise(values)]
    same=[v for t,v in returns[-1260:] if t.astimezone(ZoneInfo('America/New_York')).weekday()==contract['target_weekday'] and v!=0]
    if len(same)<50:raise ValueError('50_same_weekday_strict_moves_required')
    beta=(1+sum(v>0 for v in same))/(2+len(same));recent=[v for _,v in returns[-252:]];sigma=stdev(recent)
    if sigma<=0:raise ValueError('nonzero_return_variance_required')
    gauss=1-NormalDist(mean(recent),sigma).cdf(0)
    estimates_by_model=[(MODELS[0],beta,len(same)),(MODELS[1],gauss,len(recent))];result=[]
    for name,up,n in estimates_by_model:
        probability=up if contract['selected_outcome']=='Up' else 1-up
        result.append({'model_id':name,'model_version':name,'model_sha256':next(d['model_sha256'] for d in definitions() if d['model_id']==name),
            'feature_version':'sp500-current-observed-cash-closes-v1','domain':'finance','event_id':contract['market']['event_id'],
            'market_id':contract['market']['market_id'],'token_id':contract['market']['token_id'],'probability':probability,
            'probability_semantics':'binary_event_probability','lower_probability':0.,'upper_probability':1.,'uncertainty':1.,
            'training_observations':n,'last_source_observation':values[-1][0].isoformat(),'dataset_sha256':digest(p),
            'evidence_ids':[e.id],'evidence_cutoff':now.isoformat(),'event_end_time':contract['period_end'],'rules_sha256':contract['rules_sha256'],
            'contract':contract,'source_lineages':['FRED:SP500:cash-index'],'calibration_status':'unvalidated_research',
            'target_conditioning':contract['conditioning'],'unconditional_contract_probability':False,'market_probability':None,
            'limitations':['No verified historical WSJ prices, holidays, revised-vintage availability or independent held-out calibration',
                          'FRED is the exact cash-index asset but cannot by itself prove WSJ contract settlement',
                          'Models share one source and cannot count as independent confirmation'],
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return result


async def fresh_book(market,book,clock):
    now=at(clock());b=OrderBookSnapshot.model_validate(book.model_dump() if hasattr(book,'model_dump') else book) if book is not None else None
    if b is not None and b.source in PUBLIC_BOOK_SOURCES and b.market_id==market.market_id and assess_book(b,now,max_spread=.05,expected_token=market.token_id).healthy:return b
    adapter=OperationalPolymarketAdapter(clock=clock)
    try:b=await adapter.book(market.market_id,market.token_id)
    finally:await adapter.close()
    if assess_book(b,at(clock()),max_spread=.05,expected_token=market.token_id).healthy:return b
    # Extra research contracts are not necessarily in the shared WS universe.
    # Observe a genuine full native snapshot/update; NEVER restamp old books.
    async with asyncio.timeout(9):
        async with connect(WS,open_timeout=5,close_timeout=1,ping_interval=None,max_size=1024**2) as socket:
            await socket.send(json.dumps({'assets_ids':[market.token_id],'type':'market'}))
            while True:
                message=await socket.recv()
                if message in {'PING','PONG'}:
                    if message=='PING':await socket.send('PONG')
                    continue
                events=json.loads(message);events=events if isinstance(events,list) else [events]
                for raw in events:
                    if raw.get('event_type')!='book' or raw.get('asset_id')!=market.token_id:continue
                    received=at(clock());native=normalize_book(raw,market.market_id,market.token_id,received)
                    values=native.model_dump(exclude={'id'});values['source']=WS
                    native=OrderBookSnapshot(id=stable_id('native-extra-research-book',values),**values)
                    if assess_book(native,received,max_spread=.05,expected_token=market.token_id).healthy:
                        BOOK_RAW[native.id]={'native_full_book':raw,'received_at':received.isoformat(),'source':WS,'raw_sha256':digest(raw)}
                        while len(BOOK_RAW)>16:BOOK_RAW.pop(next(iter(BOOK_RAW)))
                        return native


def bind_predictions(results,m,b,created):
    if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:
        raise ValueError('fresh_native_two_sided_external_book_required')
    midpoint=(b.bids[0].price+b.asks[0].price)/2
    return [{**r,'timestamp':created.isoformat(),'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),
        'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'market_probability':None,'market_expected_payout':midpoint,
        **({'native_book_provenance':BOOK_RAW[b.id]} if b.id in BOOK_RAW else {})} for r in results]


async def forecast(market,book,*,clock):
    m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market);mapped=supports(m,cutoff=clock())
    if not mapped['supported']:return {'forecasts':[],'evidence':[],'rejections':mapped['reasons']}
    evidence=()
    try:
        evidence=await collect(clock=clock);cutoff=at(clock());results=estimates(mapped['contract'],evidence,cutoff=cutoff)
        b=await fresh_book(m,book,clock);created=at(clock())
        return {'forecasts':bind_predictions(results,m,b,created),'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
    except (ValueError,TypeError,KeyError,httpx.HTTPError,TimeoutError) as error:
        return {'forecasts':[],'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[str(error)[:180]]}


def replay(forecast,evidence,*,as_of):
    f=forecast;created=at(f['timestamp']);cutoff=at(f['evidence_cutoff'])
    if not cutoff<=created<=at(as_of):raise ValueError('prospective_financial_cutoff_required')
    m=MarketSnapshot.model_validate(f['market']);b=OrderBookSnapshot.model_validate(f['book'])
    if digest(m.model_dump(mode='json'))!=digest(f['contract']['market']):raise ValueError('exact_forecast_market_contract_binding_required')
    results=estimates(f['contract'],evidence,cutoff=cutoff);expected=next(r for r in results if r['model_id']==f['model_id'])
    for k,v in expected.items():
        if digest(f.get(k))!=digest(v):raise ValueError('financial_model_replay_mismatch:'+k)
    bound=bind_predictions([expected],m,b,created)[0]
    replay_book_provenance(f,m,b,created)
    if f['book_id']!=bound['book_id'] or f['book_sha256']!=bound['book_sha256'] or f['market_expected_payout']!=bound['market_expected_payout']:
        raise ValueError('native_financial_book_binding_mismatch')
    return {'verified':True,'model_id':f['model_id'],'dataset_sha256':f['dataset_sha256'],'research_only':True,'trading_authority':False,'certification_authority':False}


def replay_book_provenance(f,m,b,created):
    if not f.get('native_book_provenance'):return
    p=f['native_book_provenance'];raw=p['native_full_book'];received=at(p['received_at'])
    if p['source']!=WS or raw.get('event_type')!='book' or raw.get('asset_id')!=m.token_id or digest(raw)!=p['raw_sha256'] or received>created:
        raise ValueError('exact_native_full_book_raw_evidence_required')
    native=normalize_book(raw,m.market_id,m.token_id,received);values=native.model_dump(exclude={'id'});values['source']=WS
    native=OrderBookSnapshot(id=stable_id('native-extra-research-book',values),**values)
    if digest(native.model_dump(mode='json'))!=digest(b.model_dump(mode='json')):raise ValueError('native_book_raw_snapshot_mismatch')


async def verify_outcome(forecast,*,directory,clock):
    if at(clock())<at(forecast['event_end_time']):return {'verified':False,'reason':'SPX_session_not_completed'}
    return {'verified':False,'reason':'authoritative_WSJ_historical_close_and_primary_session_proof_unavailable_no_substitution'}


def replay_outcome(result,study,forecast,*,evidence_root,as_of):
    raise ValueError('authoritative_WSJ_close_outcome_proof_unavailable')
