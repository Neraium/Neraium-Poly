"""Actual FRED cash-index inputs, with strict settlement-source separation.

The observed financial universe uses Pyth active-month WTI/session barriers or
subjective IPO events. SP500 daily cash closes cannot stand in for those inputs,
Yahoo settlement records, Pyth minute extrema, futures rolls or session calendars.
This working source/research function is deliberately NOT a registered market
forecasting model until an exact supported contract is observed and audited.
"""

import csv
import hashlib
import io
import math
from datetime import UTC, datetime
from itertools import pairwise
from statistics import stdev

import httpx
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest

URL='https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500'


def _at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('aware financial source cutoff required')
    return value.astimezone(UTC)


def definitions():
    return [] # No observed exact-reference contract qualifies for enrollment.


def supports(market,*,cutoff):
    m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market);now=_at(cutoff)
    if m.available_at>now or m.timestamp>now:reason='financial_market_available_after_cutoff'
    elif 'app.pyth.com' in m.resolution_source:reason='Pyth_futures_minute_history_roll_and_session_evidence_required'
    elif 'IPO' in m.question:reason='independent_IPO_event_probability_model_unavailable'
    elif 'yahoo' in m.resolution_source.lower():reason='exact_Yahoo_reference_required_FRED_is_not_a_settlement_substitute'
    else:reason='audited_exact_financial_contract_and_reference_required'
    return {'supported':False,'reasons':[reason],'contract':None}


async def collect_history(*,clock):
    requested=_at(clock())
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        response=await client.get(URL);response.raise_for_status()
        if len(response.content)>512*1024:raise ValueError('FRED_source_byte_budget_exceeded')
        raw=response.content.decode('utf8')
    received=_at(clock());payload={'url':URL,'series':'SP500','price_definition':'daily_cash_index_close',
        'requested_at':requested.isoformat(),'retrieved_at':received.isoformat(),'raw_utf8':raw,
        'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'historical_availability':'not_verified_before_this_retrieval'}
    e=DomainEvidence(id=digest(['FRED-SP500',payload]),timestamp=received,available_at=received,retrieved_at=received,
        source=URL,domain='finance',provider='Federal Reserve Bank of St. Louis FRED',source_id='SP500',
        content_sha256=digest(payload),payload=payload,independent_of_polymarket=True,qualification='qualified_research')
    replay_history(e,cutoff=received)
    return e


def replay_history(evidence,*,cutoff):
    e=DomainEvidence.model_validate(evidence.model_dump() if hasattr(evidence,'model_dump') else evidence);now=_at(cutoff);p=e.payload
    if (e.source!=URL or e.source_id!='SP500' or e.domain!='finance' or not e.independent_of_polymarket
        or max(e.timestamp,e.available_at,e.retrieved_at)>now or digest(p)!=e.content_sha256
        or p.get('url')!=URL or p.get('series')!='SP500' or p.get('price_definition')!='daily_cash_index_close'
        or hashlib.sha256(p['raw_utf8'].encode()).hexdigest()!=p['raw_sha256']
        or not _at(p['requested_at'])<=_at(p['retrieved_at'])<=e.available_at):
        raise ValueError('exact_causal_FRED_source_identity_and_hash_required')
    reader=csv.DictReader(io.StringIO(p['raw_utf8']))
    if reader.fieldnames!=['observation_date','SP500']:raise ValueError('exact_FRED_SP500_schema_required')
    rows=[];last=None
    for row in reader:
        day=datetime.strptime(row['observation_date'],'%Y-%m-%d').date()
        if day>now.date() or last and day<=last:raise ValueError('future_or_reordered_financial_observation')
        last=day
        if row['SP500'].strip() in {'','.'}:continue
        value=float(row['SP500'])
        if not math.isfinite(value) or value<=0:raise ValueError('finite_positive_cash_index_close_required')
        rows.append({'date':day.isoformat(),'close':value})
    if not 200<=len(rows)<=4000:raise ValueError('bounded_200_observation_FRED_history_required')
    return rows


def terminal_research_probability(evidence,*,threshold,business_days,cutoff):
    """Falsifiable daily-return control; not a forecast of any unmapped contract."""
    rows=replay_history(evidence,cutoff=cutoff)
    if not math.isfinite(threshold) or threshold<=0 or type(business_days) is not int or not 1<=business_days<=20:
        raise ValueError('positive_threshold_and_bounded_business_horizon_required')
    training=rows[-253:];returns=[math.log(b['close']/a['close']) for a,b in pairwise(training)]
    sigma=stdev(returns)
    if sigma<=0:raise ValueError('observed_financial_return_variation_required')
    z=math.log(threshold/training[-1]['close'])/(sigma*math.sqrt(business_days))
    probability=.5*math.erfc(z/math.sqrt(2))
    return {'probability':probability,'lower_probability':0.,'upper_probability':1.,'calibration_status':'unvalidated_research',
        'training_observations':len(training),'dataset_sha256':digest(training),'source_available_at':evidence.available_at.isoformat() if hasattr(evidence,'available_at') else evidence['available_at'],
        'scope':'cash-index daily-close research only; NOT an enrolled market forecast or settlement source substitute',
        'research_only':True,'trading_authority':False,'certification_authority':False}


async def forecast(market,book,*,clock):
    del book
    return {'forecasts':[],'evidence':[],'rejections':supports(market,cutoff=clock())['reasons']}


def replay(forecast,evidence,*,as_of):
    del forecast,evidence,as_of
    raise ValueError('no_financial_market_model_enrolled_without_exact_reference')


async def verify_outcome(forecast,*,directory,clock):
    del forecast,directory,clock
    return {'status':'withheld','outcome':None,'reasons':['exact_financial_settlement_reference_not_qualified'],'trading_authority':False}
