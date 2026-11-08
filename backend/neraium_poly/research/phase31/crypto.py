"""Official Binance public-archive event labels, never native settlement proofs.

Archives are a documented public dataset, not an alternate trading API. Missing
next-day files withhold labels; access restrictions are never bypassed. Spot
archives from2025 use microseconds. Every archive, CHECKSUM and full UTC-day
sequence is replayed before selecting the exact local-day contract interval.
"""
import csv
import hashlib
import io
import math
import re
import shutil
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path

import httpx
from neraium_poly.research.phase14.contracts import DomainContract
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.sources import at
from neraium_poly.research.phase23.models import map_challenger_contract
from neraium_poly.research.phase23.outcomes import replay_forecast

ORIGIN='https://data.binance.vision/data/spot/daily/klines/'
DOCS='https://github.com/binance/binance-public-data'
TERMS='https://raw.githubusercontent.com/binance/binance-public-data/master/TERMS_AND_CONDITIONS.md'
PROTOCOL='official-binance-archive-event-v31'
TARGET='exact_Binance_completed_1m_low_at_or_below_threshold_in_ET_day'
MAX_ZIP=1024**2
MAX_CSV=4*1024**2
AUTHORITY={'research_only':True,'native_payout_verified':False,'trading_authority':False,'certification_authority':False,
    'market_baseline_comparable':True}
_CACHE={}


def _access(authorization,verifier,*,as_of):
    if not isinstance(authorization,dict) or not callable(verifier):raise TypeError('official_archive_eligible_use_authorization_required')
    if (authorization.get('purpose') not in {'noncommercial_nonproduction_research','separately_licensed'}
        or not re.fullmatch('[a-f0-9]{64}',str(authorization.get('evidence_sha256','')))
        or at(authorization['available_at'])>at(as_of)):
        raise ValueError('official_archive_eligible_use_evidence_invalid')
    proof=verifier(authorization,as_of=at(as_of))
    if not isinstance(proof,dict) or proof.get('authorized') is not True:
        raise ValueError('official_archive_eligible_use_independent_review_failed')
    return authorization


def _require_reference(forecast):
    rules=str(forecast.get('market',{}).get('resolution_rules','')).lower()
    # The preserved current rule template points to a Binance trading chart but
    # explicitly excludes spot markets. A Spot archive cannot resolve that
    # contradiction; neither a license nor a matching symbol authorizes guessing.
    if re.search(r'\bspot markets\b[^.]*\bnot be considered\b',rules):
        raise ValueError('spot_reference_rule_ambiguity_requires_review')


def _us(value):
    d=at(value)-datetime(1970,1,1,tzinfo=UTC)
    return (d.days*86400+d.seconds)*1000000+d.microseconds


def _time(value):return datetime(1970,1,1,tzinfo=UTC)+timedelta(microseconds=value)


def _contract(f):
    c=DomainContract.model_validate(f['contract']);m=c.parameters['market_snapshot']
    if (f.get('domain')!='crypto' or f.get('probability_semantics')!='binary_event_probability'
        or c.contract_type!='binance_daily_low_barrier' or not c.compatible or c.review_required
        or c.parameters.get('symbol') not in {'BTCUSDT','ETHUSDT'} or c.parameters.get('operator')!='<='
        or c.parameters.get('price_definition')!='final_minute_low' or c.parameters.get('timezone')!='America/New_York'
        or c.parameters.get('selected_outcome') not in {'Yes','No'}
        or any(f[k]!=getattr(c,k) for k in ('market_id','event_id','token_id','rules_sha256'))
        or any(f[k]!=m[k] for k in ('market_id','event_id','token_id'))):raise ValueError('exact_supported_crypto_event_required')
    rebound=map_challenger_contract(f['market'],now=at(f['evidence_cutoff']))
    if not rebound.compatible or rebound.parameters!=c.parameters or rebound.rules_sha256!=c.rules_sha256:
        raise ValueError('original_exact_crypto_rules_required')
    start,end=at(c.parameters['period_start_utc']),at(c.parameters['period_end_utc'])
    if not 23*3600<=(end-start).total_seconds()<=25*3600 or end!=at(f['event_end_time']):raise ValueError('exact_local_day_window_required')
    return c,start,end


def archive_url(symbol,day):
    if symbol not in {'BTCUSDT','ETHUSDT'} or not isinstance(day,date):raise ValueError('supported_archive_identity_required')
    filename=f'{symbol}-1m-{day.isoformat()}.zip'
    return ORIGIN+f'{symbol}/1m/'+filename


def parse_archive(raw,checksum,*,symbol,day):
    """Complete validated UTC day, normalized integer microseconds, Decimal prices."""
    url=archive_url(symbol,day);name=url.rsplit('/',1)[-1]
    if not 0<len(raw)<=MAX_ZIP or not 0<len(checksum)<=512:raise ValueError('bounded_official_archive_required')
    expected=hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(re.escape(expected)+r'\s+\*?'+re.escape(name)+r'\s*',checksum.decode('ascii')):
        raise ValueError('official_archive_checksum_mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist()
        if len(entries)!=1 or entries[0].filename!=name[:-4]+'.csv' or not 0<entries[0].file_size<=MAX_CSV or entries[0].flag_bits&1:
            raise ValueError('single_exact_bounded_archive_csv_required')
        body=archive.read(entries[0])
    rows=[];begin=_us(datetime.combine(day,datetime.min.time(),UTC));unit=1 if day>=date(2025,1,1) else 1000
    for i,row in enumerate(csv.reader(io.StringIO(body.decode('ascii')))):
        if i>=1440 or len(row)!=12:raise ValueError('complete_exact_1440_row_archive_required')
        opened=int(row[0])*unit;closed=int(row[6])*unit
        if opened!=begin+i*60000000 or closed!=opened+60000000-unit:
            raise ValueError('exact_archive_unit_sequence_and_candle_boundary_required')
        o,h,l,c=map(Decimal,row[1:5]);volumes=[Decimal(row[j]) for j in (5,7,9,10)]
        if (any(not v.is_finite() or v<=0 for v in (o,h,l,c)) or l>min(o,c) or h<max(o,c) or l>h
            or any(not v.is_finite() or v<0 for v in volumes) or int(row[8])<0):raise ValueError('finite_consistent_official_ohlc_required')
        rows.append({'open_us':opened,'close_us':closed,'low':l})
    if len(rows)!=1440:raise ValueError('complete_exact_1440_row_archive_required')
    return rows


def _derive(f,archives,*,as_of):
    c,start,end=_contract(f);now=at(as_of);start_us,end_us=_us(start),_us(end)
    if now<end:raise ValueError('exact_crypto_event_window_not_yet_complete')
    period=[];days=[];refs=[]
    for day,raw,checksum,evidence in archives:
        if day in days:raise ValueError('duplicate_official_archive_day')
        days.append(day);refs.append(evidence);period.extend(r for r in parse_archive(raw,checksum,symbol=c.parameters['symbol'],day=day) if start_us<=r['open_us']<end_us)
    period.sort(key=lambda x:x['open_us'])
    if not period or period[0]['open_us']!=start_us:raise ValueError('official_archive_event_prefix_missing')
    if any(b['open_us']!=a['open_us']+60000000 for a,b in pairwise(period)):raise ValueError('official_archive_event_prefix_gap')
    threshold=Decimal(str(c.parameters['threshold']));hits=[r for r in period if r['low']<=threshold]
    complete=period[-1]['open_us']+60000000==end_us
    if not hits and not complete:raise ValueError('official_next_day_archive_missing_complete_ET_window')
    if hits:
        first=hits[0]
        if not _us(f['timestamp'])<first['close_us']:raise ValueError('barrier_outcome_precedes_original_forecast')
        lower,upper=_time(first['close_us']),_time(first['open_us']+60000000)
    else:lower=upper=end
    yes=int(bool(hits));outcome=yes if c.parameters['selected_outcome']=='Yes' else 1-yes
    return {'symbol':c.parameters['symbol'],'period_start_utc':start.isoformat(),'period_end_utc':end.isoformat(),
        'threshold':float(threshold),'selected_outcome':c.parameters['selected_outcome'],'yes_barrier_outcome':yes,'outcome':outcome,
        'event_end_lower':lower.isoformat(),'event_end_upper':upper.isoformat(),'complete_event_window':complete,
        'observed_event_minutes':len(period),'event_group_id':digest(['official-binance-barrier-event',c.parameters['symbol'],start.isoformat(),end.isoformat()]),
        'archive_dates':[d.isoformat() for d in sorted(days)],'archive_revision_policy':'frozen source CHECKSUM version; native settlement/corrections not inferred'}


async def _fetch(client,url,clock,limit):
    now=at(clock());cached=_CACHE.get(url)
    if cached is not None and 0<=(now-at(cached[1]['retrieved_at'])).total_seconds()<60:return cached
    async with client.stream('GET',url,follow_redirects=False) as r:
        r.raise_for_status();raw=bytearray()
        async for chunk in r.aiter_bytes():
            raw.extend(chunk)
            if len(raw)>limit:raise ValueError('official_archive_download_byte_limit')
    body=bytes(raw);ref={'source_url':url,'retrieved_at':at(clock()).isoformat(),'content_sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)}
    _CACHE[url]=(body,ref)
    while len(_CACHE)>8:_CACHE.pop(next(iter(_CACHE)))
    return body,ref


def _root(path):
    p=Path(path).absolute()
    if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise ValueError('official_archive_directory_alias')
    p.mkdir(parents=True,exist_ok=True);return p


def _save(root,raw,ref,suffix):
    ref={**ref,'raw_file':ref['content_sha256']+suffix};p=root/ref['raw_file']
    if p.exists():
        if p.is_symlink() or p.read_bytes()!=raw:raise ValueError('official_archive_existing_content_conflict')
    else:
        with p.open('xb') as handle:handle.write(raw)
    return ref


async def verify_crypto_event(forecast,*,directory,clock=None,access_authorization=None,access_verifier=None):
    clock=clock or (lambda:datetime.now(UTC));now=at(clock())
    try:
        authorization=_access(access_authorization,access_verifier,as_of=now)
        _require_reference(forecast)
        c,start,end=_contract(forecast)
        if now<end:return {'status':'pending','event_result_verified':False,'reason':'exact_crypto_event_window_not_yet_complete',**AUTHORITY}
        root=_root(directory)
        if shutil.disk_usage(root).free<100*1024**3+8*1024**2:raise ValueError('event_result_filesystem_reserve')
        namespace='official-crypto-'+digest(forecast['id'])[:24];sub=_root(root/namespace);archives=[];missing=[]
        day=start.date()
        async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
            for _ in range(2):
                url=archive_url(c.parameters['symbol'],day)
                try:
                    raw,a=await _fetch(client,url,clock,MAX_ZIP);checksum,b=await _fetch(client,url+'.CHECKSUM',clock,512)
                    refs=[_save(sub,raw,a,'.zip'),_save(sub,checksum,b,'.checksum')]
                    parse_archive(raw,checksum,symbol=c.parameters['symbol'],day=day)
                    archives.append((day,raw,checksum,{'day':day.isoformat(),'archive':refs[0],'checksum':refs[1]}))
                except httpx.HTTPStatusError as e:
                    if e.response.status_code!=404:raise
                    missing.append({'source_url':url,'status':404,'observed_at':at(clock()).isoformat()})
                day+=timedelta(days=1)
                if datetime.combine(day,datetime.min.time(),UTC)>=end:break
        try:result=_derive(forecast,archives,as_of=at(clock()))
        except ValueError as e:
            return {'status':'pending','event_result_verified':False,'reason':str(e),'missing_archives':missing,
                'official_evidence':[x[3] for x in archives],'evidence_directory':namespace,**AUTHORITY}
        return {'status':'official_event_verified','event_result_verified':True,'verification_protocol':PROTOCOL,'target':TARGET,
            **{k:forecast[k] for k in ('event_id','market_id','token_id','rules_sha256')},'forecast_id':forecast['id'],
            'original_forecast_sha256':digest(forecast),'available_at':at(clock()).isoformat(),'official_result':result,
            'event_group_id':result['event_group_id'],'official_evidence':[x[3] for x in archives],
            'evidence_directory':namespace,'documentation':DOCS,'dataset_terms':TERMS,'access_authorization':authorization,'native_settlement_status':'not_verified_separate_existing_gate_required',**AUTHORITY}
    except (ValueError,TypeError,KeyError,OSError,InvalidOperation,zipfile.BadZipFile,httpx.HTTPError,UnicodeError) as e:
        return {'status':'withheld','event_result_verified':False,'reason':type(e).__name__+':'+str(e)[:180],**AUTHORITY}


def replay_crypto_event(result,study,forecast,*,evidence_root,as_of,access_verifier=None):
    now=at(as_of);_access(result.get('access_authorization'),access_verifier,as_of=now);_require_reference(forecast);c,_start,end=_contract(forecast)
    if (result.get('status')!='official_event_verified' or result.get('market_baseline_comparable') is not True or result.get('verification_protocol')!=PROTOCOL or result.get('target')!=TARGET or result.get('event_result_verified') is not True
        or result.get('native_payout_verified') is not False or result.get('trading_authority') is not False or result.get('certification_authority') is not False
        or any(result.get(k)!=forecast[k] for k in ('event_id','market_id','token_id','rules_sha256'))
        or result.get('forecast_id')!=forecast['id'] or result.get('original_forecast_sha256')!=digest(forecast)
        or sum(f.get('id')==forecast['id'] and digest(f)==digest(forecast) for f in study.get('forecasts',[]))!=1
        or not at(forecast['timestamp'])<=at(study['available_at'])<end or not at(result['available_at'])<=now):
        raise ValueError('original_prospective_crypto_event_binding_required')
    replay_forecast(study,forecast,as_of=now)
    root=Path(evidence_root).absolute();namespace='official-crypto-'+digest(forecast['id'])[:24]
    if result.get('evidence_directory')!=namespace or root.is_symlink() or any(p.is_symlink() for p in root.parents):raise ValueError('official_crypto_evidence_root_mismatch')
    sub=root/namespace
    if sub.is_symlink():raise ValueError('official_crypto_evidence_directory_alias')
    refs=result['official_evidence']
    if not isinstance(refs,list) or not 1<=len(refs)<=2:raise ValueError('bounded_exact_crypto_archive_evidence_required')
    archives=[]
    for item in refs:
        day=date.fromisoformat(item['day']);url=archive_url(c.parameters['symbol'],day);raw=[]
        for key,suffix,expected,limit in [('archive','.zip',url,MAX_ZIP),('checksum','.checksum',url+'.CHECKSUM',512)]:
            ref=item[key];name=ref['content_sha256']+suffix;p=sub/name
            if (ref['raw_file']!=name or not re.fullmatch(r'[a-f0-9]{64}'+re.escape(suffix),name)
                or p.is_symlink() or not p.resolve().is_relative_to(sub.resolve()) or not 0<p.stat().st_size<=limit):raise ValueError('official_crypto_source_path_or_size_invalid')
            body=p.read_bytes()
            if (len(body)!=ref['bytes'] or hashlib.sha256(body).hexdigest()!=ref['content_sha256'] or ref['source_url']!=expected
                or not at(ref['retrieved_at'])<=at(result['available_at'])<=now or at(ref['retrieved_at'])<end):raise ValueError('official_crypto_source_integrity_availability_or_identity_mismatch')
            raw.append(body)
        archives.append((day,*raw,item))
    derived=_derive(forecast,archives,as_of=now)
    if derived!=result['official_result'] or result.get('event_group_id')!=derived['event_group_id']:
        raise ValueError('official_crypto_result_replay_mismatch')
    outcome=derived['outcome'];p=forecast['probability'];q=forecast['market_probability'];likelihood=p if outcome else 1-p
    if (type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1
        or type(q) not in (int,float) or not math.isfinite(q) or not 0<=q<=1):raise ValueError('finite_original_model_and_market_probability_required')
    if at(study['available_at'])>=at(derived['event_end_lower']):raise ValueError('original_publication_not_before_outcome_known')
    return {'event_result_verified':True,'verification_protocol':PROTOCOL,**{k:forecast[k] for k in ('event_id','market_id','token_id')},
        'forecast_id':forecast['id'],'event_group_id':derived['event_group_id'],'outcome':outcome,'available_at':result['available_at'],
        'event_end_lower':derived['event_end_lower'],'event_end_upper':derived['event_end_upper'],
        'brier':(p-outcome)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,
        'log_loss_status':'finite' if likelihood>0 else 'positive_infinity','market_brier':(q-outcome)**2,
        'market_log_loss':-math.log(q if outcome else 1-q) if (q if outcome else 1-q)>0 else None,
        'official_evidence_sha256':digest(refs),'proof_sha256':digest(result),
        'score_scope':'exact official Binance event target; not independently verified native payout or demonstrated profitability',**AUTHORITY}
