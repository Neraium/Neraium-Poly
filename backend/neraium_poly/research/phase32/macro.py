"""Official first-release macro results, never native payout or trade authority.

Existing exact parsers are reused; completion-conditioned research results are
scorable without conflating independent official evidence with on-chain payout.
"""
import hashlib
import json
import math
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24 import economics as fed
from neraium_poly.research.phase25 import economics as ons
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase26 import outcomes as storage
from neraium_poly.research.phase31.macro import macro_readiness

PROTOCOL='official-macro-event-v32'
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False,
           'native_payout_verified':False,'market_baseline_comparable':False}


def _mapping(f):
    c=f['contract'];kind=c['kind'];module=ons if kind=='uk_gdp_qoq_first_release' else fed if kind=='fomc' else None
    if module is None:raise ValueError('exact_supported_macro_event_required_CPI_missingness_not_imputed')
    m=MarketSnapshot.model_validate(f['market']);cutoff=at(f['evidence_cutoff']);created=at(f['timestamp'])
    mapped=module.supports(m,cutoff=cutoff)
    models=ons.MODELS if module is ons else fed.FOMC_MODELS
    if (not mapped.get('supported') or mapped['contract']!=c or f.get('domain')!='economics'
        or f.get('model_id') not in models or f.get('probability_semantics')!='binary_event_probability'
        or any(f[k]!=getattr(m,k) for k in ('market_id','token_id','event_id'))
        or f['rules_sha256']!=hashlib.sha256(m.resolution_rules.encode()).hexdigest()
        or not m.timestamp<=m.available_at<=cutoff<=created):raise ValueError('exact_original_macro_contract_identity_required')
    boundary=at(c['release_at']) if module is ons else datetime.fromisoformat(c['meeting_date']).replace(tzinfo=ZoneInfo('America/New_York')).replace(hour=14).astimezone(UTC)
    if not created<boundary:raise ValueError('macro_forecast_must_precede_official_event_boundary')
    return c,module,boundary


def macro_outcome_inventory(entries,*,as_of):
    """Exact current inventory, not fabricated labels for upcoming releases."""
    base=macro_readiness(entries,as_of=as_of)
    rows=[r for r in base['rows'] if r['domain']=='economics']
    groups={r['canonical_group_id'] for r in rows if r['canonical_group_id']}
    return {'schema_version':'phase32-macro-outcome-inventory-v1','as_of':at(as_of).isoformat(),
        'forecasts':len(rows),'reviewed_event_groups':len(groups),'rows':rows,
        'official_event_verification_implemented':['uk_gdp_initial_release','scheduled_FOMC_statement_and_target_upper'],
        'CPI_missing_reference_policy':'no interpolation, denominator fabrication, or unsupported fallback outcome',
        'counts':{name:sum(r['category']==name for r in rows) for name in {r['category'] for r in rows}},
        'outcome_verification_performed':False,'official_events_verified':None,'native_settlements_verified':None,**AUTHORITY}


def _namespace(f):return 'official-macro-'+digest(f['id'])[:24]


async def _get(client,url,clock):
    async with client.stream('GET',url) as response:
        response.raise_for_status()
        if str(response.url)!=url:raise ValueError('exact_official_macro_request_no_redirect_required')
        body=bytearray()
        async for chunk in response.aiter_bytes():
            if len(body)+len(chunk)>storage.MAX_BYTES:raise ValueError('bounded_official_macro_source_required')
            body.extend(chunk)
    if not body:raise ValueError('nonempty_official_macro_source_required')
    raw=bytes(body)
    return raw,{'source_url':url,'retrieved_at':at(clock()).isoformat(),'content_sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def _final(c,module,raw,refs,available):
    if module is ons:
        if len(raw)!=1 or refs[0]['source_url']!=ons.bulletin_url(c):raise ValueError('exact_target_ONS_firstrelease_source_required')
        result=ons.parse_bulletin(c,raw[0],available_at=available)
        published=re.findall(r'"datePublished":\s*"([^"]+)"',raw[0].decode())
        publication=at(published[0]);day=at(result['publication_day_lower_bound'])
        if not day<=publication<day+timedelta(days=1) or publication>available:raise ValueError('exact_ONS_publication_time_required')
        return {'outcome':result['expected'],'publication_at':publication.isoformat(),'value':result['value'],
                'event_group_id':digest(['official-ONS-first-release',c['series_id'],c['target_period']]),'target':'initial_ONS_GDP_quarter_on_quarter'}
    if len(raw)!=3 or refs[-1]['source_url']!=_statement_url(c):raise ValueError('exact_FOMC_sources_required')
    evidence=[DomainEvidence.model_validate_json(r) for r in raw[:2]]
    if [e.source for e in evidence]!=[fed.FOMC_CALENDAR,fed.FRED_UPPER] or [r['source_url'] for r in refs[:2]]!=[fed.FOMC_CALENDAR,fed.FRED_UPPER]:raise ValueError('exact_FOMC_calendar_and_target_upper_required')
    if _statement_url(c).removeprefix('https://www.federalreserve.gov') not in evidence[0].payload['raw_response_utf8']:
        raise ValueError('official_calendar_linked_statement_required')
    if any(e.retrieved_at!=at(refs[i]['retrieved_at']) or max(e.timestamp,e.available_at)>available for i,e in enumerate(evidence)):
        raise ValueError('FOMC_source_availability_mismatch')
    final=fed._final_fomc(c,evidence,raw[2],available)
    if not final['verified']:raise ValueError(final['reason'])
    if not at(final['publication_at'])<=at(refs[2]['retrieved_at'])<=available:raise ValueError('official_macro_publication_after_receipt')
    return {'outcome':final['expected'],'publication_at':at(final['publication_at']).isoformat(),
            'before_upper':final['before_upper'],'after_upper':final['after_upper'],
            'event_group_id':digest(['official-FederalReserve-scheduled-meeting',c['meeting_date']]),'target':'scheduled_target_upper_bound_no_change'}


def _statement_url(c):return 'https://www.federalreserve.gov/newsevents/pressreleases/monetary'+c['meeting_date'].replace('-','')+'a.htm'


async def verify_macro_event(f,*,directory,clock=None):
    clock=clock or (lambda:datetime.now(UTC));now=at(clock())
    try:
        c,module,boundary=_mapping(f)
        eligible=boundary if module is ons else boundary.replace(hour=0)+timedelta(days=2)
        if now<eligible:return {'status':'pending','event_result_verified':False,'reason':'official_macro_event_or_corroborating_history_not_yet_due',**AUTHORITY}
        root=storage._root(directory)
        if shutil.disk_usage(root).free<100*1024**3+16*1024**2:raise ValueError('official_macro_filesystem_reserve')
        sub=storage._root(root/_namespace(f));raw=[];refs=[]
        async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
            if module is fed:
                sources=await fed._collect_fomc(clock=clock)
                for e in sources:
                    value=json.dumps(e.model_dump(mode='json'),sort_keys=True,separators=(',',':')).encode()
                    if len(value)>storage.MAX_BYTES:raise ValueError('bounded_official_macro_source_required')
                    raw.append(value);refs.append({'source_url':e.source,'retrieved_at':e.retrieved_at.isoformat(),'content_sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value)})
            value,ref=await _get(client,ons.bulletin_url(c) if module is ons else _statement_url(c),clock)
            raw.append(value);refs.append(ref)
        available=at(clock())
        if any(at(r['retrieved_at'])>available for r in refs):raise ValueError('official_macro_receipt_after_verification_clock')
        final=_final(c,module,raw,refs,available)
        if not at(f['timestamp'])<at(final['publication_at']):raise ValueError('prospective_macro_publication_cutoff_required')
        saved=[storage._save(sub,value,ref,'.json' if module is fed and i<2 else '.html') for i,(value,ref) in enumerate(zip(raw,refs,strict=True))]
        return {'status':'official_event_verified','event_result_verified':True,'verification_protocol':PROTOCOL,
            'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
            'rules_sha256':f['rules_sha256'],'original_forecast_sha256':digest(f),'evidence_directory':_namespace(f),
            'official_evidence':saved,'official_result':final,'event_group_id':final['event_group_id'],
            'available_at':available.isoformat(),'native_settlement_status':'separate_native_proof_not_verified',**AUTHORITY}
    except (ValueError,TypeError,KeyError,OSError,httpx.HTTPError) as error:
        return {'status':'withheld','event_result_verified':False,'reason':type(error).__name__+':'+str(error)[:180],**AUTHORITY}


def replay_macro_event(result,study,f,*,evidence_root,as_of):
    now=at(as_of);c,module,boundary=_mapping(f)
    if (result.get('verification_protocol')!=PROTOCOL or result.get('status')!='official_event_verified'
        or result.get('event_result_verified') is not True or any(result.get(k) is not v for k,v in AUTHORITY.items())
        or any(result.get(k)!=f[k] for k in ('event_id','market_id','token_id','rules_sha256'))
        or result.get('forecast_id')!=f['id'] or result.get('original_forecast_sha256')!=digest(f)
        or sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study.get('forecasts',[]))!=1
        or not at(f['timestamp'])<=at(study['available_at'])<boundary):raise ValueError('original_prospective_macro_target_binding_required')
    byid={e['id']:e for e in study['evidence']}
    if len(byid)!=len(study['evidence']):raise ValueError('unique_original_macro_sources_required')
    if module.replay(f,[byid[e] for e in f['evidence_ids']],as_of=now).get('verified') is not True:raise ValueError('original_macro_model_source_replay_failed')
    root=Path(evidence_root).absolute();sub=root/_namespace(f)
    if root.is_symlink() or any(x.is_symlink() for x in root.parents) or sub.is_symlink() or result['evidence_directory']!=_namespace(f):raise ValueError('official_macro_evidence_root_mismatch')
    refs=result['official_evidence'];raw=[]
    if not isinstance(refs,list) or len(refs)!=(1 if module is ons else 3):raise ValueError('exact_official_macro_source_count_required')
    for i,ref in enumerate(refs):
        suffix='.json' if module is fed and i<2 else '.html';name=ref['content_sha256']+suffix;p=sub/name
        if (ref['raw_file']!=name or not re.fullmatch(r'[a-f0-9]{64}\.(json|html)',name) or p.is_symlink()
            or not p.resolve().is_relative_to(sub.resolve()) or not 0<p.stat().st_size<=storage.MAX_BYTES):raise ValueError('official_macro_source_path_or_size_invalid')
        body=p.read_bytes()
        if (len(body)!=ref['bytes'] or hashlib.sha256(body).hexdigest()!=ref['content_sha256']
            or not at(ref['retrieved_at'])<=at(result['available_at'])<=now):raise ValueError('official_macro_source_hash_or_time_mismatch')
        raw.append(body)
    final=_final(c,module,raw,refs,max(at(r['retrieved_at']) for r in refs))
    if final!=result['official_result'] or final['event_group_id']!=result['event_group_id'] or not at(study['available_at'])<at(final['publication_at']):raise ValueError('official_macro_result_or_prospectivity_mismatch')
    p=f['probability'];y=final['outcome']
    if type(p) not in (float,int) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('finite_macro_probability_required')
    likelihood=p if y else 1-p
    return {'event_result_verified':True,'verification_protocol':PROTOCOL,'forecast_id':f['id'],'event_id':f['event_id'],
        'market_id':f['market_id'],'token_id':f['token_id'],'event_group_id':final['event_group_id'],'outcome':y,
        'event_end_lower':final['publication_at'],'event_end_upper':final['publication_at'],'available_at':result['available_at'],
        'brier':(p-y)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,'market_brier':None,'market_log_loss':None,
        'official_evidence_sha256':digest(refs),'proof_sha256':digest(result),'score_scope':'conditional official macro result, not native payout or market superiority',**AUTHORITY}
