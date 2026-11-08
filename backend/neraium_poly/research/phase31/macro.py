"""Official macro input qualification, separate from forecasts or payout labels.

Current GDP/SPX/FOMC forecasts target future events. CPI October2026 has a
source-specific structural absence; querying more years never fabricates it.
"""
import hashlib
import html
import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

CPI_API='https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0'
CPI_POLICY='https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi-faq.htm'
GDP_CALENDAR='https://www.ons.gov.uk/releasecalendar?keywords=GDP&release-type=type-upcoming&sort=date-newest'
REFERENCES={'spx':'https://www.wsj.com/market-data/stocks',
    'uk_gdp':'https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/gdpfirstquarterlyestimateuk/previousreleases',
    'fomc':'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
    'cpi':'https://www.bls.gov/bls/news-release/cpi.htm'}
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False,
    'native_payout_verified':False,'forecast_probability':None}
MAX_BYTES=2*1024**2


def _text(raw):return ' '.join(html.unescape(re.sub('<[^>]+>',' ',raw)).split())


def _source(evidence,url,now):
    if (evidence.get('source_url')!=url or evidence.get('source_timestamp') is not None
        or not at(evidence['requested_at'])<=at(evidence['retrieved_at'])<=at(evidence['available_at'])<=now
        or (now-at(evidence['available_at'])).total_seconds()>21600
        or not 0<len(evidence['raw_utf8'].encode())<=MAX_BYTES
        or hashlib.sha256(evidence['raw_utf8'].encode()).hexdigest()!=evidence['content_sha256']):
        raise ValueError('exact_official_macro_source_hash_and_availability_required')
    return evidence['raw_utf8']


async def collect_cpi_availability(*,clock=None,client=None):
    """Two bounded official GETs; actual receipt time, no historical availability claim."""
    clock=clock or (lambda:datetime.now(UTC));owned=client is None
    client=client or httpx.AsyncClient(timeout=10,follow_redirects=False)
    evidence=[];errors=[]
    try:
        for url in (CPI_API,CPI_POLICY):
            requested=at(clock());body=bytearray()
            async with client.stream('GET',url) as response:
                if response.status_code!=200 and url==CPI_POLICY:
                    errors.append({'source_url':url,'status_code':response.status_code,'observed_at':at(clock()).isoformat(),
                        'reason':'optional_official_publication_policy_unavailable_no_access_bypass'})
                    continue
                response.raise_for_status()
                if str(response.url)!=url:raise ValueError('official_macro_redirect_not_authorized')
                async for part in response.aiter_bytes():
                    if len(body)+len(part)>MAX_BYTES:raise ValueError('official_macro_source_byte_budget')
                    body.extend(part)
            received=at(clock());raw=bytes(body).decode('utf8')
            evidence.append({'source_url':url,'requested_at':requested.isoformat(),'retrieved_at':received.isoformat(),
                'available_at':received.isoformat(),'source_timestamp':None,'raw_utf8':raw,
                'content_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                'availability_scope':'earliest verified availability is this receipt, not historical publication'})
        return {'evidence':evidence,'evidence_sha256':digest(evidence),'available_at':at(clock()).isoformat(),'source_errors':errors,**AUTHORITY}
    finally:
        if owned:await client.aclose()


def cpi_qualification(bundle,*,target_year,target_month,as_of):
    """Qualify the exact prior-year denominator; never impute a missing CPI level."""
    now=at(as_of)
    if type(target_year) is not int or type(target_month) is not int or not 1<=target_month<=12:raise ValueError('exact_CPI_target_month_required')
    evidence=bundle['evidence']
    if len(evidence) not in (1,2) or digest(evidence)!=bundle['evidence_sha256'] or at(bundle['available_at'])>now:
        raise ValueError('bounded_exact_official_CPI_sources_required')
    raw=json.loads(_source(evidence[0],CPI_API,now));policy=_text(_source(evidence[1],CPI_POLICY,now)) if len(evidence)==2 else ''
    series=raw['Results']['series']
    if raw.get('status')!='REQUEST_SUCCEEDED' or len(series)!=1 or series[0].get('seriesID')!='CUUR0000SA0':
        raise ValueError('exact_official_CPI_U_series_required')
    rows=[r for r in series[0]['data'] if r.get('year')==str(target_year-1) and r.get('period')==f'M{target_month:02d}']
    if len(rows)>1:raise ValueError('duplicate_official_CPI_denominator')
    denominator=None;missing='denominator_month_not_returned'
    if rows:
        row=rows[0]
        if not isinstance(row.get('value'),str):raise ValueError('official_CPI_index_string_required')
        try:
            value=Decimal(row['value'])
            if not value.is_finite() or value<=0:raise ValueError('positive_official_CPI_denominator_required')
            denominator=str(value);missing=None
        except InvalidOperation:
            notes=row.get('footnotes',[])
            if row.get('value')=='-' and any(n.get('code')=='X' and '2025' in n.get('text','') and 'lapse' in n.get('text','').lower() for n in notes):
                missing='official_2025_lapse_data_not_collected_or_published'
            else:missing='official_CPI_denominator_missing_without_reviewed_reason'
    policy_exact=bool(target_year==2026 and target_month==10 and re.search(
        r'BLS will not publish 12.month percent changes for October 2026 for indexes where October 2025 data are not available',policy,re.IGNORECASE))
    policy_applies=policy_exact and missing=='official_2025_lapse_data_not_collected_or_published'
    reasons=[]
    if missing:reasons.append(missing)
    if len(evidence)==1:reasons.append('official_publication_policy_not_machine_verified')
    if policy_applies:reasons+=['official_target_12_month_change_not_to_be_published','contract_fallback_interpretation_requires_review']
    return {'schema_version':'phase31-CPI-source-qualification-v1','target_year':target_year,'target_month':target_month,
        'series_id':'CUUR0000SA0','denominator_period':f'{target_year-1}-{target_month:02d}',
        'denominator_value':denominator,'denominator_available':denominator is not None,
        'source_structural_missingness':missing=='official_2025_lapse_data_not_collected_or_published','publication_policy_source_verified':len(evidence)==2,'target_annual_change_publication_supported':not policy_applies if denominator is not None or policy_applies else None,
        'numerical_probability_supported':False,'fallback_outcome_verified':False,'outcome':None,
        'status':'structural_source_blocker' if missing=='official_2025_lapse_data_not_collected_or_published' else 'denominator_only_qualified' if denominator else 'source_missingness_unresolved',
        'reasons':reasons,'evidence_sha256':bundle['evidence_sha256'],'available_at':bundle['available_at'],
        'source_urls':[CPI_API,CPI_POLICY],'scope':'current input/source-policy qualification, not a prospective probability, historical vintage or settlement',**AUTHORITY}


def macro_readiness(entries,*,as_of):
    """Source-replayed inventory; future releases never become missing outcomes."""
    now=at(as_of)
    if len(entries)>4096:raise ValueError('bounded_macro_inventory_required')
    seen={};conflicts=set();rows=[];counts=Counter();groups=set()
    for row in entries:
        if row.get('type')!='forecast':continue
        f=row['forecast'];model=f.get('model_id','')
        family=next((name for prefix,name in [('spx-','spx'),('uk-gdp-','uk_gdp'),('fomc-','fomc'),('cpi-','cpi')] if model.startswith(prefix)),None)
        if family is None:continue
        identity=f['id'];sha=row.get('forecast_sha256')
        if identity in seen:
            if seen[identity]!=sha:conflicts.add(identity)
            continue
        seen[identity]=sha
        review=row.get('review',{});descriptor=review.get('descriptor',{});reference=descriptor.get('resolution_reference')
        end=at(f['event_end_time']);created=at(f['timestamp']);available=at(row['available_at'])
        reasons=[]
        if row.get('replay_verified') is not True or not created<=available<=now:category='SOURCE_PROVENANCE_MISSING';reasons.append('original_model_source_replay_or_availability_required')
        elif reference!=REFERENCES[family]:category='REFERENCE_IDENTITY_MISMATCH';reasons.append('exact_contract_reference_required_no_proxy_substitution')
        elif now<end:category='NOT_YET_MATURE';reasons.append('event_reference_window_or_release_has_not_completed')
        else:
            category='OFFICIAL_RESULT_REVIEW_REQUIRED'
            reasons.append({'spx':'exact_WSJ_official_close_and_prior_trading_session_required',
                'uk_gdp':'ONS_original_initial_bulletin_not_revised_current_series_required',
                'fomc':'calendar_linked_official_statement_and_before_after_range_required',
                'cpi':'exact_initial_CPI_release_or_reviewed_fallback_required'}[family])
        group=review.get('canonical_group_id')
        if group:groups.add(group)
        counts[category]+=1
        rows.append({'forecast_id':identity,'family':family,'domain':f['domain'],'model_id':model,'event_id':f['event_id'],
            'market_id':f['market_id'],'token_id':f['token_id'],'forecast_timestamp':created.isoformat(),
            'original_available_at':available.isoformat(),'reference_event_cutoff':end.isoformat(),
            'cutoff_precision':'contract forecast boundary; not an asserted exact final publication time',
            'resolution_reference':reference,'canonical_group_id':group,'category':category,'reasons':reasons,**AUTHORITY})
    if conflicts:
        rows=[r for r in rows if r['forecast_id'] not in conflicts];counts=Counter(r['category'] for r in rows);counts['CONFLICTING_ORIGINAL_FORECAST_IDENTITY']=len(conflicts)
        groups={r['canonical_group_id'] for r in rows if r['canonical_group_id']}
    return {'schema_version':'phase31-macro-readiness-v1','as_of':now.isoformat(),'forecasts':len(rows),
        'canonical_event_groups':len(groups),'counts':dict(counts),'rows':rows,'official_outcomes_verified':0,
        'statistical_independence_verified':False,'effective_independent_sample_size':None,
        'scope':'source-specific macro readiness, not outcome verification or certified independent events',**AUTHORITY}


def qualify_cpi_market(market,bundle,*,as_of):
    """Apply structural missingness only to an exactly reviewed native contract."""
    from neraium_poly.research.phase24.economics import _cpi_supports
    now=at(as_of);mapped=_cpi_supports(market,cutoff=now)
    if not mapped['supported']:
        return {'status':'unsupported_contract','reasons':mapped['reasons'],'numerical_probability_supported':False,**AUTHORITY}
    c=mapped['contract'];m=c['market'];result=cpi_qualification(bundle,target_year=c['target_year'],target_month=c['target_month'],as_of=now)
    return {**result,'market_id':m['market_id'],'event_id':m['event_id'],'token_id':m['token_id'],
        'rules_sha256':c['rules_sha256'],'scheduled_release_at':c['release_at'],
        'statistical_model_estimation_blocked':not result['denominator_available'],
        'contract_fallback_review_required':result['source_structural_missingness']}
