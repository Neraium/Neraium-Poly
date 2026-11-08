"""Exact AWC station-day event results, separate from native payouts/finality.

A verified reference snapshot scores the existing completion-conditioned weather
research target only. Material-error corrections, fallback and native settlement
remain separate gates; neither this module nor its labels authorize execution.
"""
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.weather import ORIGIN, PATH, _final_weather, at
from neraium_poly.research.phase26.outcomes import _fetch, _root

PROTOCOL='official-AWC-station-day-event-v32'
TARGET='routine_AWC_station_local_day_high_as_published_after_following_day_freeze'
AUTHORITY={'research_only':True,'native_payout_verified':False,'trading_authority':False,
    'certification_authority':False,'market_baseline_comparable':False}
MAX_BYTES=1024**2


def _mapping(f):
    model=f['model_id']
    module=importlib.import_module('neraium_poly.research.phase24.weather' if model in ('metar-diurnal-analog-v24.1','metar-recent-climatology-v24.1') else 'neraium_poly.research.phase25.weather')
    if model not in module.MODELS or f.get('domain')!='weather':raise ValueError('reviewed_weather_model_required')
    market=MarketSnapshot.model_validate(f['market']);cutoff=at(f['evidence_cutoff']);created=at(f['timestamp'])
    mapped=module.supports(market,cutoff=cutoff);c=f['contract']
    if (not mapped['supported'] or mapped['contract']!=c or any(f[k]!=getattr(market,k) for k in ('event_id','market_id','token_id'))
        or not cutoff<=created<at(c['period_end']) or at(f['event_end_time'])!=at(c['period_end'])
        or f['rules_sha256']!=hashlib.sha256(market.resolution_rules.encode()).hexdigest()):
        raise ValueError('exact_original_weather_contract_identity_required')
    end=at(c['period_end']);q=parse_qs(urlsplit(c['source_url']).query);source_end=at(q['date'][0])
    url=ORIGIN+PATH+'?'+urlencode({'ids':c['station'],'format':'json','date':source_end.strftime('%Y-%m-%dT%H:%M:%SZ'),'hours':30})
    return module,c,end,source_end,url


def parse_station_result(c,raw,*,observed_at,source_end):
    """A complete exact-station reference read, never a missing-data fallback."""
    now=at(observed_at);source_end=at(source_end)
    if not 0<len(raw)<=MAX_BYTES:raise ValueError('bounded_AWC_reference_source_required')
    rows=json.loads(raw)
    if not isinstance(rows,list) or not 1<=len(rows)<400:raise ValueError('complete_nontruncated_AWC_result_required')
    clean={}
    for row in rows:
        obs=datetime.fromtimestamp(row['obsTime'],UTC);receipt=at(row['receiptTime']);text=row['rawOb'].strip()
        if (row['icaoId']!=c['station'] or not source_end-timedelta(hours=30)<=obs<=source_end
            or not obs<=receipt<=now):raise ValueError('AWC_station_window_or_availability_mismatch')
        if text.startswith('SPECI'):continue
        match=re.match(r'^(?:METAR\s+)?'+re.escape(c['station'])+r'\s+(\d{6})Z\s',text)
        if match is None or match[1]!=obs.strftime('%d%H%M'):raise ValueError('raw_METAR_observation_timestamp_mismatch')
        prior=clean.get(obs)
        if prior and prior['rawOb']!=row['rawOb']:raise ValueError('ambiguous_routine_report_versions')
        if prior is None or at(prior['receiptTime'])<receipt:clean[obs]=row
    result=_final_weather(c,json.dumps(list(clean.values())).encode(),now)
    if not result['verified']:raise ValueError(result['reason'])
    if not at(c['period_end'])<=result['freeze']<=source_end<=now:raise ValueError('exact_following_day_freeze_not_observed')
    return {'outcome':result['expected'],'station':c['station'],'station_local_date':c['day'],
        'timezone':c['timezone'],'units':'degrees_Celsius_rounded_half_up','resolution_value':result['resolution_value'],
        'period_start':c['period_start'],'period_end':c['period_end'],'reference_freeze':result['freeze'].isoformat(),
        'observed_at':now.isoformat(),'routine_reports':len(clean),
        'target':TARGET,'material_error_correction_status':'not_adjudicated_native_gate_preserved'}


def _save(root,raw,item):
    """Publish a durable immutable source; an interruption cannot expose a prefix."""
    item={**item,'raw_file':hashlib.sha256(raw).hexdigest()+'.json'};dest=root/item['raw_file']
    if dest.exists():
        if dest.is_symlink() or dest.read_bytes()!=raw:raise ValueError('AWC_existing_source_integrity_conflict')
        return item
    fd,name=tempfile.mkstemp(prefix='.awc-pending-',dir=root)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:os.link(name,dest)
        except FileExistsError:
            if dest.is_symlink() or dest.read_bytes()!=raw:raise ValueError('AWC_atomic_publication_conflict')
        directory_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
    finally:os.unlink(name)
    return item


async def verify_weather_event(f,*,directory,clock=None):
    clock=clock or (lambda:datetime.now(UTC));now=at(clock())
    try:
        _module,c,_end,source_end,url=_mapping(f)
        if now<source_end:return {'status':'pending','event_result_verified':False,'reason':'complete_exact_AWC_reference_window_not_available',**AUTHORITY}
        root=_root(directory)
        if shutil.disk_usage(root).free<100*1024**3+2*MAX_BYTES:raise ValueError('weather_reference_filesystem_reserve')
        namespace='weather-reference-'+digest([c['station'],c['day'],url])[:24];sub=_root(root/namespace)
        async with httpx.AsyncClient(timeout=10,follow_redirects=False,headers={'User-Agent':'Neraium-Poly bounded official weather research/0.32'}) as client:
            raw,item=await _fetch(client,url,clock)
        official=parse_station_result(c,raw,observed_at=item['retrieved_at'],source_end=source_end)
        ref=_save(sub,raw,item)
        return {'status':'official_event_verified','event_result_verified':True,'verification_protocol':PROTOCOL,
            'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
            'rules_sha256':f['rules_sha256'],'original_forecast_sha256':digest(f),'available_at':at(clock()).isoformat(),
            'official_result':official,'official_evidence':[ref],'evidence_directory':namespace,
            'event_group_id':digest(['AWC-station-local-day',c['station'],c['day']]),'target':TARGET,
            'native_settlement_status':'not_verified_separate_native_proof_required',**AUTHORITY}
    except (ValueError,TypeError,KeyError,OSError,httpx.HTTPError) as error:
        return {'status':'withheld','event_result_verified':False,'reason':type(error).__name__+':'+str(error)[:180],**AUTHORITY}


def replay_weather_event(result,study,f,*,evidence_root,as_of):
    now=at(as_of);module,c,end,source_end,url=_mapping(f)
    if (result.get('verification_protocol')!=PROTOCOL or result.get('event_result_verified') is not True
        or any(result.get(k)!=v for k,v in AUTHORITY.items()) or result.get('target')!=TARGET
        or result.get('forecast_id')!=f['id'] or result.get('original_forecast_sha256')!=digest(f)
        or any(result.get(k)!=f[k] for k in ('event_id','market_id','token_id','rules_sha256'))
        or sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study.get('forecasts',[]))!=1
        or not at(f['timestamp'])<=at(study['available_at'])<end<=source_end<=at(result['available_at'])<=now):
        raise ValueError('exact_original_prospective_weather_event_proof_required')
    if module.replay(f,study['evidence'],as_of=now).get('verified') is not True:raise ValueError('original_weather_model_source_replay_required')
    root=Path(evidence_root).absolute();namespace='weather-reference-'+digest([c['station'],c['day'],url])[:24]
    if result['evidence_directory']!=namespace or root.is_symlink() or any(p.is_symlink() for p in root.parents):raise ValueError('weather_evidence_directory_identity_mismatch')
    sub=root/namespace;refs=result['official_evidence']
    if sub.is_symlink() or not isinstance(refs,list) or len(refs)!=1:raise ValueError('one_exact_AWC_reference_required')
    ref=refs[0];expected=ref['content_sha256']+'.json';path=sub/expected
    if (not re.fullmatch(r'[a-f0-9]{64}\.json',expected) or ref['raw_file']!=expected or path.is_symlink()
        or not path.resolve().is_relative_to(sub.resolve()) or not 0<path.stat().st_size<=MAX_BYTES):raise ValueError('weather_reference_path_or_size_invalid')
    raw=path.read_bytes()
    if (len(raw)!=ref['bytes'] or hashlib.sha256(raw).hexdigest()!=ref['content_sha256'] or ref['source_url']!=url
        or not source_end<=at(ref['retrieved_at'])<=at(result['available_at'])<=now):raise ValueError('weather_reference_provenance_or_hash_mismatch')
    final=parse_station_result(c,raw,observed_at=ref['retrieved_at'],source_end=source_end)
    if final!=result['official_result'] or result['event_group_id']!=digest(['AWC-station-local-day',c['station'],c['day']]):raise ValueError('weather_reference_event_result_mismatch')
    p=f['probability'];outcome=final['outcome'];likelihood=p if outcome else 1-p
    if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('finite_original_weather_probability_required')
    return {'event_result_verified':True,'verification_protocol':PROTOCOL,'forecast_id':f['id'],'event_id':f['event_id'],
        'market_id':f['market_id'],'token_id':f['token_id'],'event_group_id':result['event_group_id'],
        'outcome':outcome,'available_at':result['available_at'],'event_end_lower':final['period_end'],
        'event_end_upper':final['reference_freeze'],'reference_freeze':final['reference_freeze'],'resolution_value':final['resolution_value'],
        'brier':(p-outcome)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,
        'log_loss_status':'finite' if likelihood>0 else 'positive_infinity','market_brier':None,'market_log_loss':None,
        'score_scope':'conditional official station-day reference, not native payout or market superiority',
        'official_evidence_sha256':digest(refs),'proof_sha256':digest(result),**AUTHORITY}
