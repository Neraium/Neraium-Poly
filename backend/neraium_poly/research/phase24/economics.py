"""Observed official CPI-U data and explicitly uncalibrated first-release research."""
import hashlib
import html
import json
import math
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from statistics import NormalDist, mean, stdev
from zoneinfo import ZoneInfo

import httpx
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest

ORIGIN='https://api.bls.gov'
PATH='/publicAPI/v1/timeseries/data/CUUR0000SA0'
SERIES='CUUR0000SA0'
SOURCE='https://www.bls.gov/bls/news-release/cpi.htm'
MODELS=('cpi-yoy-increment-gaussian-v24.1','cpi-yoy-ridge-ar1-v24.1')
RULE_TEMPLATE='This is a market about inflation over the 12-month period ending {month_year}, before seasonal adjustment, as reported by the Bureau of Labor Statistics.\n\nThis market will resolve to the percentage change in the Consumer Price Index (CPI) over the 12-month period ending in {month_year} according to the monthly Bureau of Labor Statistics (BLS) report.\n\nThe resolution source for this market will be the BLS Consumer Price Index report released for {month_year} (https://www.bls.gov/bls/news-release/cpi.htm), currently scheduled to be released on {release_date}, at 8:30 AM ET. Resolution of this market will take place upon release of the aforementioned data.\n\nNote: the resolution source for this market will be the official monthly BLS CPI news release, which reports inflation over 12-month periods to only one decimal point (e.g., 2.9%). Thus, this is the level of precision that will be used when resolving the market.\n\nIf the BLS does not release the relevant figures on the scheduled date, this market may remain open up until the scheduled release time of the next CPI report (https://www.bls.gov/schedule). If the information is not released by that time, this market will resolve according to the figures of the most recent previous month with available data.'
_CACHE=None


def at(v):
    t=v if isinstance(v,datetime) else datetime.fromisoformat(v)
    if t.tzinfo is None:raise ValueError('aware_economic_timestamp_required')
    return t.astimezone(UTC)


def _cpi_definitions():
    sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return [{'model_id':name,'model_version':name,'model_sha256':digest([sha,name]),
        'feature_version':'causal_current_CPIU_NSA_snapshot_yoy_differences-v1','hypothesis':hypothesis,
        'input_requirements':['official BLS CUUR0000SA0 raw response','at least18consecutive historical year-over-year observations','exact pending CPI firstrelease rules'],
        'performance_criteria':['independently verified firstrelease scores','chronological calibration and same-time market comparison'],
        'failure_conditions':['inflation regime change','revisions/corrections','index rounding vs published percentage','release delays'],
        'risk_assumptions':'Uncalibrated research only; uncertainty[0,1]; no operational admission',
        'source_independence':'Models share one BLS snapshot; no independent confirmation',
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for name,hypothesis in zip(MODELS,['Next first-release YoY modeled from recent index-implied YoY increments',
                                         'Regularized AR(1) YoY model with empirical innovation variance'])]


def _cpi_supports(market,*,cutoff):
    try:
        now=at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if isinstance(market,MarketSnapshot) else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or max(m.timestamp,m.available_at)>now or m.outcome not in {'Yes','No'} or not m.end_time or m.end_time<=now):
            raise ValueError('causal_active_CPI_market_required')
        q=re.fullmatch(r'Will annual inflation be (-?\d+\.\d)%(?: or (more|less))? in ([A-Z][a-z]+)\?',m.question)
        period=re.search(r'12-month period ending ([A-Z][a-z]+) (20\d{2}), before seasonal adjustment',m.resolution_rules)
        release=re.search(r'currently scheduled to be released on ([A-Z][a-z]+ \d{1,2}, 20\d{2}), at 8:30 AM ET',m.resolution_rules)
        if not q or not period or not release or m.resolution_source!=SOURCE:raise ValueError('exact_CPI_U_firstrelease_contract_required')
        k,tail,month=q.groups();pmonth,year=period.groups()
        if month!=pmonth:raise ValueError('CPI_question_period_mismatch')
        target=datetime.strptime(f'{month} {year}','%B %Y').replace(tzinfo=UTC)
        released=datetime.strptime(release.group(1),'%B %d, %Y').replace(hour=8,minute=30,tzinfo=ZoneInfo('America/New_York')).astimezone(UTC)
        if not now<released<=now+timedelta(days=45) or released<=target:raise ValueError('pending_near_term_CPI_release_required')
        expected=RULE_TEMPLATE.format(month_year=month+' '+year,release_date=release.group(1))
        if m.resolution_rules!=expected:raise ValueError('CPI_rule_version_or_fallback_changed')
        return {'supported':True,'reasons':[],'contract':{'target_year':int(year),'target_month':target.month,
            'threshold':k,'tail':tail,'selected_outcome':m.outcome,'release_at':released.isoformat(),
            'source_url':SOURCE,'series_id':SERIES,'variable':'CPI-U allitems UScityaverage 12month change before seasonal adjustment',
            'precision':'official first-release one decimal percent','rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
            'calendar_status':'scheduled time is the exact contract definition; official calendar HTML currently unavailable',
            'market':m.model_dump(mode='json')}}
    except (ValueError,TypeError,KeyError) as error:
        return {'supported':False,'reasons':[str(error)[:180]],'contract':None}


async def _collect_cpi(*,clock):
    global _CACHE
    now=at(clock())
    if _CACHE is not None and 0<=(now-_CACHE.available_at).total_seconds()<21600:return (_CACHE,)
    async with httpx.AsyncClient(timeout=10,follow_redirects=False,headers={'User-Agent':'Neraium-Poly public research/0.24'}) as client:
        response=await client.get(ORIGIN+PATH);response.raise_for_status();raw=response.content
    received=at(clock())
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_CPI_response_required')
    payload={'request_url':str(response.url),'raw_response_utf8':raw.decode(),
        'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'series_id':SERIES,
        'vintage_scope':'current observed snapshot only; historical firstrelease availability is NOT established'}
    _CACHE=DomainEvidence(id=digest(['BLS-current-CPIU',payload,received.isoformat()]),timestamp=received,available_at=received,
        source=ORIGIN+PATH,domain='economics',provider='US Bureau of Labor Statistics',source_id=SERIES,
        retrieved_at=received,source_timestamp=None,content_sha256=digest(payload),payload=payload,
        qualification='qualified_research',independent_of_polymarket=True,
        missingness=('historical_firstrelease_vintages','independent_release_calendar','historical_executable_books'))
    return (_CACHE,)


def _estimate_cpi(contract,evidence,*,cutoff):
    now=at(cutoff);mapped=_cpi_supports(contract['market'],cutoff=now)
    if not mapped['supported'] or mapped['contract']!=contract:raise ValueError('CPI_exact_contract_replay_required')
    if len(evidence)!=1:raise ValueError('one_official_CPI_snapshot_required')
    e=DomainEvidence.model_validate(evidence[0].model_dump() if hasattr(evidence[0],'model_dump') else evidence[0]);p=e.payload
    if (e.source!=ORIGIN+PATH or e.source_id!=SERIES or e.domain!='economics' or e.provider!='US Bureau of Labor Statistics'
        or not e.independent_of_polymarket or e.qualification!='qualified_research' or max(e.timestamp,e.available_at,e.retrieved_at)>now
        or p['request_url']!=ORIGIN+PATH or digest(p)!=e.content_sha256
        or hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest()!=p['raw_response_sha256']):
        raise ValueError('official_causal_CPI_raw_provenance_required')
    raw=json.loads(p['raw_response_utf8']);series=raw['Results']['series']
    if raw['status']!='REQUEST_SUCCEEDED' or len(series)!=1 or series[0]['seriesID']!=SERIES:raise ValueError('exact_CPI_series_required')
    values={};missing=[];periods=set()
    for row in series[0]['data']:
        if row['period']=='M13':continue
        if not re.fullmatch('M(?:0[1-9]|1[012])',row['period']):raise ValueError('monthly_CPI_observations_required')
        year,month=int(row['year']),int(row['period'][1:]);key=year*12+month-1
        if key in periods:raise ValueError('duplicate_CPI_month')
        periods.add(key)
        if row['value']=='-' and any(x.get('code')=='X' for x in row.get('footnotes',[])):
            missing.append(key);continue
        try:value=Decimal(row['value'])
        except InvalidOperation:raise ValueError('unavailable_CPI_index_value') from None
        if not value.is_finite() or value<=0 or key in values:raise ValueError('positive_unique_CPI_index_required')
        if datetime(year,month,1,tzinfo=UTC)>now:raise ValueError('future_CPI_observation')
        values[key]=value
    if not 30<=len(values)<=120:raise ValueError('30_to120monthly_CPI_levels_required')
    target=contract['target_year']*12+contract['target_month']-1
    if target-12 not in values:raise ValueError('target_year_ago_CPI_index_unavailable_no_imputation')
    if max(periods)!=target-1 or min(periods)+len(periods)-1!=max(periods):raise ValueError('contiguous_pre_target_CPI_reporting_periods_required')
    yoy=[(k,float(100*(values[k]/values[k-12]-1))) for k in sorted(values) if k-12 in values]
    if len(yoy)<18:raise ValueError('18_index_implied_yoy_observations_required')
    if yoy[-1][0]!=target-1:raise ValueError('latest_pre_target_CPI_yoy_unavailable')
    pairs=[(a[1],b[1]) for a,b in pairwise(yoy) if b[0]-a[0]==1]
    if len(pairs)<12:raise ValueError('12_adjacent_valid_CPI_innovations_required')
    ys=[v for _,v in yoy];increments=[b-a for a,b in pairs]
    mu=ys[-1]+mean(increments[-12:]);sigma=stdev(increments[-12:])
    xs,nexts=tuple(zip(*pairs,strict=True));mx,my=mean(xs),mean(nexts)
    beta=sum((x-mx)*(y-my) for x,y in zip(xs,nexts,strict=True))/(sum((x-mx)**2 for x in xs)+1)
    intercept=my-beta*mx;ar_mu=intercept+beta*ys[-1];ar_sigma=stdev([y-intercept-beta*x for x,y in zip(xs,nexts,strict=True)])
    results=[];k=float(contract['threshold'])
    for definition,location,scale in zip(_cpi_definitions(),[mu,ar_mu],[sigma,ar_sigma],strict=True):
        if not math.isfinite(scale) or scale<=0:raise ValueError('empirical_CPI_innovation_variance_required')
        distribution=NormalDist(location,scale);yes=1-distribution.cdf(k-.05) if contract['tail']=='more' else distribution.cdf(k+.05) if contract['tail']=='less' else distribution.cdf(k+.05)-distribution.cdf(k-.05)
        probability=yes if contract['selected_outcome']=='Yes' else 1-yes;m=MarketSnapshot.model_validate(contract['market'])
        results.append({**definition,'domain':'economics','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
            'probability':min(1.,max(0.,probability)),'probability_semantics':'binary_event_probability',
            'lower_probability':0.,'upper_probability':1.,'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_model_uncertainty_not_sampling_interval'},
            'evidence_cutoff':now.isoformat(),'event_end_time':contract['release_at'],'rules_sha256':contract['rules_sha256'],
            'evidence_ids':[e.id],'source_lineages':['BLS:'+SERIES],'contract':contract,
            'dataset_sha256':digest([(k,str(v)) for k,v in sorted(values.items())]),'training_observations':len(yoy),
            'training_index_months':len(values),'missing_index_months':missing,'latest_index_implied_yoy':ys[-1],
            'predicted_location_percent':location,'innovation_scale_percent':scale,
            'independent_of_polymarket':True,'calibration_status':'unvalidated_research','brier':None,'log_loss':None,
            'conditioning':'normal scheduled official firstrelease; no delayed-release fallback or exceptional correction',
            'unconditional_contract_probability':False,'market_comparison_status':'conditional_release_probability_not_unconditional_token_payout',
            'limitations':['Current source vintages were genuinely available now; historical firstrelease vintages are unverified',
                'Index-implied historical YoY is a model proxy, not a verified firstrelease training label',
                'No independent calendar retrieval or consensus evidence; no forecast skill or execution edge established'],
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return results


async def _forecast_cpi(market,book,*,clock):
    now=at(clock());m=MarketSnapshot.model_validate(market);b=OrderBookSnapshot.model_validate(book);mapped=_cpi_supports(m,cutoff=now)
    if not mapped['supported']:return {'forecasts':[],'evidence':[],'rejections':mapped['reasons']}
    evidence=()
    try:
        if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or not assess_book(b,now,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('fresh_native_CPI_book_required')
        evidence=await _collect_cpi(clock=clock);cutoff=at(clock());results=_estimate_cpi(mapped['contract'],evidence,cutoff=cutoff);created=at(clock())
        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('CPI_book_stale_after_source_collection')
        return {'forecasts':[{**r,'timestamp':created.isoformat(),'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),
            'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'market_probability':None,'market_expected_payout':(b.bids[0].price+b.asks[0].price)/2} for r in results],
            'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
    except (ValueError,TypeError,KeyError,httpx.HTTPError) as error:return {'forecasts':[],'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[str(error)[:180]]}


def _replay_cpi(forecast,evidence,*,as_of):
    f=forecast;now=at(as_of)
    if not at(f['evidence_cutoff'])<=at(f['timestamp'])<=now:raise ValueError('CPI_forecast_time_binding_required')
    selected=[DomainEvidence.model_validate(x) for x in evidence if x['id'] in f['evidence_ids']]
    result=next(x for x in _estimate_cpi(f['contract'],selected,cutoff=at(f['evidence_cutoff'])) if x['model_id']==f['model_id'])
    if any(f.get(k)!=v for k,v in result.items()):raise ValueError('CPI_independent_model_replay_failed')
    m=MarketSnapshot.model_validate(f['market']);b=OrderBookSnapshot.model_validate(f['book'])
    if b.source not in PUBLIC_BOOK_SOURCES or b.exchange!=m.exchange or digest(b.model_dump(mode='json'))!=f['book_sha256'] or b.market_id!=m.market_id or not assess_book(b,at(f['timestamp']),max_spread=.05,expected_token=m.token_id).healthy:
        raise ValueError('CPI_original_native_book_binding_required')
    if f['market_probability'] is not None or f['market_expected_payout']!=(b.bids[0].price+b.asks[0].price)/2:raise ValueError('CPI_conditional_baseline_binding_required')
    return {'verified':True,'forecast_id':f.get('id'),'research_only':True,'trading_authority':False}



def _final_cpi(c,raw):
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_firstrelease_required')
    text=' '.join(html.unescape(re.sub('<[^>]+>',' ',raw.decode())).split());month=datetime(c['target_year'],c['target_month'],1).strftime('%B')
    if not re.search(r'CONSUMER PRICE INDEX\s*[-–—]\s*'+month+r'\s+'+str(c['target_year']),text,re.IGNORECASE):return {'verified':False,'reason':'exact_initial_CPI_release_month_required'}
    match=re.search(r'The all items index (rose|increased|fell|decreased) (\d+\.\d) percent for the 12 months ending '+month,text,re.IGNORECASE)
    if not match:return {'verified':False,'reason':'exact_published_firstrelease_yoy_figure_required'}
    value=Decimal(match.group(2))*(-1 if match.group(1).lower() in {'fell','decreased'} else 1);k=Decimal(c['threshold'])
    yes=int(value>=k if c['tail']=='more' else value<=k if c['tail']=='less' else value==k);expected=yes if c['selected_outcome']=='Yes' else 1-yes
    release=at(c['release_at'])
    published=re.search(r'8:30\s*a\.?m\.?\s*\(ET\)\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?,?\s*([A-Z][a-z]+ \d{1,2}, 20\d{2})',text,re.IGNORECASE)
    if not published:return {'verified':False,'reason':'actual_official_firstrelease_publication_time_required'}
    release=datetime.strptime(published.group(1),'%B %d, %Y').replace(hour=8,minute=30,tzinfo=ZoneInfo('America/New_York')).astimezone(UTC)
    return {'verified':True,'expected':expected,'resolution_value':str(value),'publication_at':release}


async def _verify_cpi(forecast,*,directory,clock):
    from neraium_poly.research.phase12.contracts import SettlementProofReference
    from neraium_poly.research.phase12.outcome_collector import (
        acquire_verified_outcome,
        verify_collected_outcome,
    )
    f=forecast;c=f['contract'];now=at(clock());release=at(c['release_at'])
    if now<release:return {'verified':False,'reason':'official_CPI_firstrelease_pending'}
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        response=await client.get(SOURCE)
    if response.status_code!=200:return {'verified':False,'reason':'official_firstrelease_source_unavailable','http_status':response.status_code}
    raw=response.content
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_CPI_release_required')
    observed=at(clock());final=_final_cpi(c,raw)
    if not final['verified']:return final
    expected,value,release=(final[k] for k in ['expected','resolution_value','publication_at'])
    m=MarketSnapshot.model_validate(f['market']);ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],
        timestamp=at(f['timestamp']),evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    directory=Path(directory);location=directory/(now.strftime('%Y%m%dT%H%M%S%fZ')+'-'+f['id'][:12]);proof=await acquire_verified_outcome(ref,m,location,clock=clock)
    if proof is None or not verify_collected_outcome(proof,m,ref,directory):return {'verified':False,'reason':'native_finalized_CPI_proof_pending'}
    if proof.payout!=expected or proof.settled_at<release:return {'verified':False,'reason':'native_CPI_payout_or_time_disagrees'}
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'outcome':expected,'resolved_at':proof.settled_at.isoformat(),
            'available_at':at(clock()).isoformat(),'proof':proof.model_dump(mode='json'),
            'evidence':[{'source_url':SOURCE,'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'retrieved_at':observed.isoformat()}],
            'resolution_value':str(value),'trading_authority':False,'certification_authority':False}


FOMC_CALENDAR='https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
FRED_UPPER='https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU&cosd=2023-01-01'
FOMC_MODELS=('fomc-scheduled-policy-frequency-v24.1','fomc-recent-policy-shrinkage-v24.1')
_FOMC_CACHE=None
FOMC_RULE_TEMPLATE='The FED interest rates are defined in this market by the upper bound of the target federal funds range. The decisions on the target federal funds range are made by the Federal Open Market Committee (FOMC) meetings.\n\nThis market will resolve to the amount of basis points the upper bound of the target federal funds rate is changed by versus the level it was prior to the Federal Reserve\'s {month_year} meeting.\n\nIf the target federal funds rate is changed to a level not expressed in the displayed options, the change will be rounded up to the nearest 25 and will resolve to the relevant bracket. (e.g. if there\'s a cut/increase of 12.5 bps it will be considered to be 25 bps)\n\nThe resolution source for this market is the FOMC’s statement after its meeting scheduled for {meeting_date} according to the official calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm.\n\nThe level and change of the target federal funds rate is also published at the official website of the Federal Reserve at https://www.federalreserve.gov/monetarypolicy/openmarket.htm.\n\nThis market may resolve as soon as the FOMC’s statement for their December meeting with relevant data is issued. If no statement is released by the end date of the next scheduled meeting, this market will resolve to the "No change" bracket.'


def _fomc_definitions():
    sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return [{'model_id':name,'model_version':name,'model_sha256':digest([sha,name]),
        'feature_version':'official-calendar-and-target-upper-before-after-meeting-v1',
        'hypothesis':hypothesis,'input_requirements':['exact FOMC meeting target-upper-bound rule','official calendar','at least16 completed regular meetings and observed target upper bounds'],
        'performance_criteria':['native and official-statement-verified outcomes','event-disjoint calibration vs ordinary frequency baseline'],
        'risk_assumptions':'Conditional uncalibrated research only; uncertainty[0,1]; no order authority',
        'failure_conditions':['policy regime change','unscheduled interventions','calendar revisions','statement fallback'],
        'source_independence':'Both models share official calendar/FRED target history, not independent corroboration',
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for name,hypothesis in zip(FOMC_MODELS,['Jeffreys-smoothed historical distribution of regular-meeting policy changes',
                                              'Recent8 regular-meeting distribution shrunk toward full historical distribution'])]


def _fomc_supports(market,*,cutoff):
    try:
        now=at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if isinstance(market,MarketSnapshot) else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or max(m.timestamp,m.available_at)>now or m.outcome not in {'Yes','No'} or not m.end_time or m.end_time<=now):
            raise ValueError('causal_active_FOMC_market_required')
        q=re.fullmatch(r'Will there be no change in Fed interest rates after the ([A-Z][a-z]+) (20\d{2}) meeting\?',m.question)
        if not q or m.resolution_source!=FOMC_CALENDAR:raise ValueError('supported_FOMC_no_change_rule_required')
        month,year=q.groups();end_month=datetime(int(year),datetime.strptime(month,'%B').month,1,tzinfo=UTC)
        match=re.search(r'meeting scheduled for ([A-Z][a-z]+) (\d{1,2})-(\d{1,2}), (20\d{2}) according',m.resolution_rules)
        if not match or match.group(1)!=month or match.group(4)!=year:raise ValueError('exact_two_day_FOMC_date_required')
        start_day,end_day=int(match.group(2)),int(match.group(3));meeting_day=datetime(int(year),end_month.month,end_day,tzinfo=ZoneInfo('America/New_York'))
        if not now<meeting_day.astimezone(UTC)<=now+timedelta(days=45):raise ValueError('pending_near_term_FOMC_meeting_required')
        expected=FOMC_RULE_TEMPLATE.format(month_year=month+' '+year,meeting_date=f'{month} {start_day}-{end_day}, {year}')
        if m.resolution_rules!=expected:raise ValueError('exact_FOMC_target_upper_rounding_and_fallback_rules_required')
        return {'supported':True,'reasons':[],'contract':{'kind':'fomc','meeting_date':meeting_day.date().isoformat(),
            'meeting_start_date':meeting_day.replace(day=start_day).date().isoformat(),'event_end_time':(meeting_day+timedelta(days=1)).astimezone(UTC).isoformat(),
            'target':'no_change_target_federal_funds_upper_bound','selected_outcome':m.outcome,
            'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),'market':m.model_dump(mode='json'),
            'calendar_url':FOMC_CALENDAR,'rate_source':FRED_UPPER,'rounding':'nonzero magnitude rounded up to25basispoints'}}
    except (ValueError,TypeError,KeyError) as error:return {'supported':False,'reasons':[str(error)[:160]],'contract':None}


def _calendar_dates(body):
    headings=list(re.finditer(r'>(20\d{2}) FOMC Meetings</a>',body))
    dates=[]
    for index,heading in enumerate(headings):
        year=int(heading.group(1));section=body[heading.end():headings[index+1].start() if index+1<len(headings) else len(body)]
        for month,days in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>(.*?)</div>',section,re.DOTALL):
            if any(flag in days.lower() for flag in ('unscheduled','notation','cancelled','canceled')):continue
            nums=re.findall(r'\d+',re.sub('<[^>]+>','',days))
            if not nums or len(nums)>2:raise ValueError('ambiguous_regular_FOMC_calendar_dates')
            actual_month=month.strip().split('/')[-1]
            try:date=datetime.strptime(f'{year} {actual_month} {nums[-1]}','%Y %B %d').date().isoformat()
            except ValueError:date=datetime.strptime(f'{year} {actual_month} {nums[-1]}','%Y %b %d').date().isoformat()
            if date in dates:raise ValueError('duplicate_regular_FOMC_meeting')
            dates.append(date)
    if len(dates)<16:raise ValueError('official_calendar_regular_meetings_required')
    return sorted(dates)


async def _collect_fomc(*,clock):
    global _FOMC_CACHE
    now=at(clock())
    if _FOMC_CACHE and 0<=(now-_FOMC_CACHE[-1].available_at).total_seconds()<21600:return _FOMC_CACHE
    evidence=[]
    async with httpx.AsyncClient(timeout=10,follow_redirects=False,headers={'User-Agent':'Neraium-Poly public research/0.24'}) as client:
        for provider,url,sid in [('Board of Governors of the Federal Reserve System',FOMC_CALENDAR,'fomc-calendar'),
                                 ('Federal Reserve Bank of St Louis',FRED_UPPER,'DFEDTARU')]:
            response=await client.get(url);response.raise_for_status();raw=response.content;received=at(clock())
            if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_FOMC_evidence_required')
            payload={'request_url':url,'raw_response_utf8':raw.decode('utf-8-sig'),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),
                     'raw_bytes_hex':raw.hex(),'availability_basis':'first observed retrieval, not historical release availability'}
            evidence.append(DomainEvidence(id=digest([sid,payload,received.isoformat()]),timestamp=received,available_at=received,
                source=url,domain='economics',provider=provider,source_id=sid,retrieved_at=received,source_timestamp=None,
                content_sha256=digest(payload),payload=payload,independent_of_polymarket=True,qualification='qualified_research',
                missingness=('historical_publication_timestamps','out_of_sample_calibration')))
    _FOMC_CACHE=tuple(evidence)
    return _FOMC_CACHE


def _fomc_inputs(evidence,cutoff):
    import csv
    import io
    if len(evidence)!=2:raise ValueError('calendar_and_target_upper_sources_required')
    objects={}
    for value in evidence:
        e=DomainEvidence.model_validate(value.model_dump() if hasattr(value,'model_dump') else value);p=e.payload
        if (e.source not in {FOMC_CALENDAR,FRED_UPPER} or e.domain!='economics'
            or (e.provider,e.source_id)!=(('Board of Governors of the Federal Reserve System','fomc-calendar') if e.source==FOMC_CALENDAR else ('Federal Reserve Bank of St Louis','DFEDTARU'))
            or not e.independent_of_polymarket or e.qualification!='qualified_research'
            or max(e.timestamp,e.available_at,e.retrieved_at)>cutoff or digest(p)!=e.content_sha256 or p['request_url']!=e.source
            or hashlib.sha256(bytes.fromhex(p['raw_bytes_hex'])).hexdigest()!=p['raw_response_sha256']
            or bytes.fromhex(p['raw_bytes_hex']).decode('utf-8-sig')!=p['raw_response_utf8'] or e.source in objects):
            raise ValueError('causal_official_FOMC_source_provenance_required')
        objects[e.source]=p['raw_response_utf8']
    dates=_calendar_dates(objects[FOMC_CALENDAR]);reader=csv.DictReader(io.StringIO(objects[FRED_UPPER]));rates={}
    if reader.fieldnames!=['observation_date','DFEDTARU']:raise ValueError('target_upper_DFEDTARU_not_effective_funds_required')
    for row in reader:
        date=datetime.strptime(row['observation_date'],'%Y-%m-%d').date()
        if date>cutoff.date():raise ValueError('future_target_rate_observation')
        if row['DFEDTARU']=='.':continue
        value=Decimal(row['DFEDTARU'])
        if not value.is_finite() or not 0<=value<=25 or date.isoformat() in rates:raise ValueError('finite_unique_target_upper_required')
        rates[date.isoformat()]=value
    if not rates or (cutoff.date()-datetime.fromisoformat(max(rates)).date()).days>3:raise ValueError('current_target_upper_rate_required')
    return dates,rates


def _estimate_fomc(contract,evidence,*,cutoff):
    now=at(cutoff);mapped=_fomc_supports(contract['market'],cutoff=now)
    if not mapped['supported'] or mapped['contract']!=contract:raise ValueError('FOMC_exact_contract_replay_required')
    dates,rates=_fomc_inputs(evidence,now)
    if contract['meeting_date'] not in dates:raise ValueError('official_calendar_does_not_corroborate_target_meeting')
    changes=[]
    for date in dates:
        day=datetime.fromisoformat(date).date();before=(day-timedelta(days=1)).isoformat();after=(day+timedelta(days=2)).isoformat()
        if date>=contract['meeting_date'] or after>now.date().isoformat():continue
        if before not in rates or after not in rates:continue
        delta=(rates[after]-rates[before])*100
        rounded=0 if delta==0 else (1 if delta>0 else -1)*int(math.ceil(abs(delta)/25)*25)
        changes.append({'date':date,'before_upper':str(rates[before]),'after_upper':str(rates[after]),'rounded_bps':rounded})
    if len(changes)<16:raise ValueError('16_completed_regular_meeting_rate_changes_required')
    unchanged=sum(x['rounded_bps']==0 for x in changes);global_yes=(unchanged+.5)/(len(changes)+1)
    recent=changes[-8:];recent_yes=(sum(x['rounded_bps']==0 for x in recent)+4*global_yes)/(len(recent)+4)
    m=MarketSnapshot.model_validate(contract['market']);results=[]
    for definition,yes in zip(_fomc_definitions(),[global_yes,recent_yes],strict=True):
        p=yes if m.outcome=='Yes' else 1-yes
        results.append({**definition,'domain':'economics','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
            'probability':p,'probability_semantics':'binary_event_probability','lower_probability':0.,'upper_probability':1.,
            'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_regime_uncertainty_not_sampling_confidence'},
            'evidence_cutoff':now.isoformat(),'event_end_time':contract['event_end_time'],'rules_sha256':contract['rules_sha256'],
            'evidence_ids':[e.id if hasattr(e,'id') else e['id'] for e in evidence],
            'source_lineages':['FederalReserve:scheduled-FOMC','FRED:DFEDTARU'], 'contract':contract,
            'dataset_sha256':digest(changes),'training_observations':len(changes),'historical_meeting_changes':changes,
            'current_observed_upper':str(rates[max(rates)]),'independent_of_polymarket':True,
            'calibration_status':'unvalidated_research','brier':None,'log_loss':None,
            'conditioning':'ordinary scheduled FOMC statement; no exceptional delayed-statement fallback',
            'unconditional_contract_probability':False,'market_comparison_status':'conditional_policy_probability_not_unconditional_token_payout',
            'limitations':['Past policy-meeting frequency is a naive falsifiable baseline, not a forecast of current committee preferences',
                'No macroeconomic covariates, consensus or market-implied rate inputs','Current authentic snapshots are not historical point-in-time vintages',
                'Before/after daily rates approximate scheduled policy outcomes; final scoring requires official statement plus native proof'],
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return results


async def _forecast_fomc(market,book,*,clock):
    now=at(clock());m=MarketSnapshot.model_validate(market);b=OrderBookSnapshot.model_validate(book);mapped=_fomc_supports(m,cutoff=now)
    if not mapped['supported']:return {'forecasts':[],'evidence':[],'rejections':mapped['reasons']}
    evidence=()
    try:
        if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or not assess_book(b,now,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('fresh_native_FOMC_book_required')
        evidence=await _collect_fomc(clock=clock);cutoff=at(clock());results=_estimate_fomc(mapped['contract'],evidence,cutoff=cutoff);created=at(clock())
        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('FOMC_book_stale_after_source_collection')
        return {'forecasts':[{**r,'timestamp':created.isoformat(),'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),
            'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'market_probability':None,'market_expected_payout':(b.bids[0].price+b.asks[0].price)/2} for r in results],
            'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
    except (ValueError,TypeError,KeyError,httpx.HTTPError) as error:return {'forecasts':[],'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[str(error)[:180]]}


def definitions():return _cpi_definitions()+_fomc_definitions()


def supports(market,*,cutoff):
    cpi=_cpi_supports(market,cutoff=cutoff)
    if cpi['supported']:return cpi
    fomc=_fomc_supports(market,cutoff=cutoff)
    return fomc if fomc['supported'] else {'supported':False,'contract':None,'reasons':sorted(set(cpi['reasons']+fomc['reasons']))}


async def forecast(market,book,*,clock):
    return await (_forecast_fomc(market,book,clock=clock) if _fomc_supports(market,cutoff=clock())['supported'] else _forecast_cpi(market,book,clock=clock))


def replay(forecast,evidence,*,as_of):
    f=forecast
    if f.get('contract',{}).get('kind')!='fomc':return _replay_cpi(f,evidence,as_of=as_of)
    if not at(f['evidence_cutoff'])<=at(f['timestamp'])<=at(as_of):raise ValueError('FOMC_forecast_temporal_binding_required')
    selected=[DomainEvidence.model_validate(x) for x in evidence if x['id'] in f['evidence_ids']];selected.sort(key=lambda e:f['evidence_ids'].index(e.id))
    result=next(x for x in _estimate_fomc(f['contract'],selected,cutoff=at(f['evidence_cutoff'])) if x['model_id']==f['model_id'])
    if any(f.get(k)!=v for k,v in result.items()):raise ValueError('FOMC_model_replay_mismatch')
    m=MarketSnapshot.model_validate(f['market']);b=OrderBookSnapshot.model_validate(f['book'])
    if b.source not in PUBLIC_BOOK_SOURCES or b.exchange!=m.exchange or digest(b.model_dump(mode='json'))!=f['book_sha256'] or b.market_id!=m.market_id or not assess_book(b,at(f['timestamp']),max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('FOMC_original_native_book_binding_required')
    if f['market_probability'] is not None or f['market_expected_payout']!=(b.bids[0].price+b.asks[0].price)/2:raise ValueError('FOMC_conditional_baseline_binding_required')
    return {'verified':True,'forecast_id':f.get('id'),'research_only':True,'trading_authority':False}



def _final_fomc(c,evidence,raw,cutoff):
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_statement_required')
    day=datetime.fromisoformat(c['meeting_date']).replace(tzinfo=ZoneInfo('America/New_York'))
    _dates,rates=_fomc_inputs(evidence,cutoff)
    text=' '.join(html.unescape(re.sub('<[^>]+>',' ',raw.decode())).split())
    if not re.search(r'target range for the federal funds rate',text,re.IGNORECASE):return {'verified':False,'reason':'exact_statement_target_range_required'}
    before=(day.date()-timedelta(days=1)).isoformat();after=(day.date()+timedelta(days=2)).isoformat()
    if before not in rates or after not in rates:return {'verified':False,'reason':'complete_before_after_target_upper_required'}
    def rate_number(value):
        value=value.strip().replace('¼','-1/4').replace('½','-1/2').replace('¾','-3/4')
        matched=re.fullmatch(r'(\d+)(?:-(\d+)/(\d+))?',value)
        if not matched:raise ValueError('unreviewed_official_target_rate_notation')
        whole,num,den=matched.groups()
        return Decimal(whole)+(Decimal(num)/Decimal(den) if num else 0)
    stated=re.search(r'(maintain|lower|raise) the target range for the federal funds rate (?:at|to) ([0-9¼½¾./ -]+?) to ([0-9¼½¾./ -]+?) percent',text,re.IGNORECASE)
    if not stated:return {'verified':False,'reason':'exact_official_target_range_required'}
    lower,upper=rate_number(stated.group(2)),rate_number(stated.group(3))
    if not 0<=lower<=upper or upper!=rates[after]:return {'verified':False,'reason':'official_statement_and_target_series_disagree'}
    action=stated.group(1).lower();delta=upper-rates[before]
    if ((action=='maintain' and delta!=0) or (action=='lower' and delta>=0) or (action=='raise' and delta<=0)):
        return {'verified':False,'reason':'official_statement_action_and_change_disagree'}
    source_day=day.strftime('%B %-d, %Y')
    if source_day not in text or not re.search(r'For release at 2:00 p\.m\.',text,re.IGNORECASE):
        return {'verified':False,'reason':'exact_official_statement_publication_date_time_required'}
    expected=int(delta==0) if c['selected_outcome']=='Yes' else int(delta!=0)
    return {'verified':True,'expected':expected,'publication_at':day.replace(hour=14),'before_upper':str(rates[before]),'after_upper':str(rates[after])}


async def verify_outcome(forecast,*,directory,clock):
    if forecast.get('contract',{}).get('kind')!='fomc':return await _verify_cpi(forecast,directory=directory,clock=clock)
    c=forecast['contract'];now=at(clock());day=datetime.fromisoformat(c['meeting_date']).replace(tzinfo=ZoneInfo('America/New_York'))
    if now<day+timedelta(days=2):return {'verified':False,'reason':'official_statement_and_effective_target_history_pending'}
    # No statement or target-level inference from a prediction-market price.
    evidence=await _collect_fomc(clock=clock);_dates,_rates=_fomc_inputs(evidence,now)
    html_body=evidence[0].payload['raw_response_utf8'];yyyymmdd=day.strftime('%Y%m%d')
    link='/newsevents/pressreleases/monetary'+yyyymmdd+'a.htm'
    if link not in html_body:return {'verified':False,'reason':'official_calendar_linked_statement_unavailable'}
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        response=await client.get('https://www.federalreserve.gov'+link)
    if response.status_code!=200:return {'verified':False,'reason':'official_FOMC_statement_unavailable'}
    raw=response.content
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_official_statement_required')
    observed=at(clock());final=_final_fomc(c,evidence,raw,observed)
    if not final['verified']:return final
    expected=final['expected']
    from neraium_poly.research.phase12.contracts import SettlementProofReference
    from neraium_poly.research.phase12.outcome_collector import (
        acquire_verified_outcome,
        verify_collected_outcome,
    )
    f=forecast;m=MarketSnapshot.model_validate(f['market']);ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],timestamp=at(f['timestamp']),evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    location=Path(directory)/(now.strftime('%Y%m%dT%H%M%S%fZ')+'-'+f['id'][:12]);proof=await acquire_verified_outcome(ref,m,location,clock=clock)
    if proof is None or not verify_collected_outcome(proof,m,ref,Path(directory)) or proof.payout!=expected or proof.settled_at<day.replace(hour=14):return {'verified':False,'reason':'native_FOMC_outcome_proof_missing_time_or_disagrees'}
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'outcome':expected,'resolved_at':proof.settled_at.isoformat(),'available_at':at(clock()).isoformat(),
        'proof':proof.model_dump(mode='json'),'evidence':[e.model_dump(mode='json') for e in evidence]+[{'source_url':str(response.url),'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'retrieved_at':observed.isoformat()}],
        'trading_authority':False,'certification_authority':False}


def replay_outcome(result,study,forecast,*,evidence_root,as_of):
    from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
    from neraium_poly.research.phase12.outcome_collector import verify_collected_outcome
    f=forecast;now=at(as_of);available=at(result['available_at'])
    if result.get('forecast_id')!=f['id'] or result.get('event_id')!=f['event_id'] or available>now:
        raise ValueError('economic_outcome_original_identity_and_availability_required')
    if sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study['forecasts'])!=1:
        raise ValueError('immutable_economic_forecast_membership_required')
    if not at(f['timestamp'])<=at(study['available_at'])<=now:raise ValueError('economic_original_study_availability_required')
    replay(f,study['evidence'],as_of=now)
    c=f['contract'];evidence=result['evidence']
    if c.get('kind')=='fomc':
        if len(evidence)!=3:raise ValueError('exact_FOMC_final_sources_required')
        statement=evidence[2];expected_url='https://www.federalreserve.gov/newsevents/pressreleases/monetary'+c['meeting_date'].replace('-','')+'a.htm'
        if statement['source_url']!=expected_url:raise ValueError('calendar_linked_official_statement_required')
        sources=[DomainEvidence.model_validate(e) for e in evidence[:2]]
        if '/newsevents/pressreleases/monetary'+c['meeting_date'].replace('-','')+'a.htm' not in sources[0].payload['raw_response_utf8']:
            raise ValueError('official_calendar_statement_link_missing')
        raw=statement['raw_response_utf8'].encode();observed=at(statement['retrieved_at'])
        if hashlib.sha256(raw).hexdigest()!=statement['raw_response_sha256'] or observed>available:
            raise ValueError('official_statement_raw_hash_or_receipt_mismatch')
        final=_final_fomc(c,sources,raw,observed)
    else:
        if len(evidence)!=1 or evidence[0]['source_url']!=SOURCE:raise ValueError('exact_official_firstrelease_source_required')
        source=evidence[0];raw=source['raw_response_utf8'].encode();observed=at(source['retrieved_at'])
        if hashlib.sha256(raw).hexdigest()!=source['raw_response_sha256'] or observed>available:
            raise ValueError('firstrelease_raw_hash_or_receipt_mismatch')
        final=_final_cpi(c,raw)
    if not final['verified']:raise ValueError(final['reason'])
    if not final['publication_at']<=observed:raise ValueError('official_source_not_available_at_recorded_receipt')
    m=MarketSnapshot.model_validate(f['market']);proof=VerifiedEventOutcome.model_validate(result['proof'])
    ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],timestamp=at(f['timestamp']),
        evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    if (not verify_collected_outcome(proof,m,ref,Path(evidence_root)) or proof.payout!=final['expected']
        or not max(at(f['timestamp']),final['publication_at'])<=proof.settled_at<=proof.available_at<=available
        or at(result['resolved_at'])!=proof.settled_at or result['outcome']!=proof.payout):
        raise ValueError('native_and_official_economic_outcome_disagree')
    p=f['probability'];outcome=final['expected'];likelihood=p if outcome else 1-p
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
        'rules_sha256':f['rules_sha256'],'outcome':outcome,'resolved_at':proof.settled_at.isoformat(),'available_at':result['available_at'],
        'brier':(p-outcome)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,
        'log_loss_status':'finite' if likelihood>0 else 'positive_infinity','market_brier':None,
        'score_scope':'conditional firstrelease/policy descriptive score, not unconditional market superiority',
        'evidence_sha256':digest(evidence),'reviewed_dependency_group':None,'trading_authority':False,'certification_authority':False}
