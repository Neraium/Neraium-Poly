"""Exact official AWC reference results for new conditional weather challengers.

These descriptive scores never verify native payout, compare against a native
market target, certify a model, or authorize an order.
"""
import asyncio
import hashlib
import json
import math
import re
import shutil
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.outcomes import DomainOutcomes, DomainOutcomeStudy
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase32.weather import (
    AUTHORITY,
    MAX_BYTES,
    TARGET,
    _fetch,
    _root,
    _save,
    parse_station_result,
)

from . import weather

PROTOCOL='official-AWC-station-day-event-v35'
KIND='WorldWeatherResearchStudy'


def _mapping(f):
    cutoff=at(f['evidence_cutoff']);created=at(f['timestamp']);mapped=weather.supports(f['market'],cutoff=cutoff);c=f['contract']
    if (f['model_id'] not in weather.MODELS or f['domain']!='weather' or not mapped['supported'] or mapped['contract']!=c
        or any(f[k]!=f['market'][k] for k in ('event_id','market_id','token_id'))
        or not cutoff<=created<at(c['period_start']) or at(f['event_end_time'])!=at(c['period_end'])
        or f['rules_sha256']!=hashlib.sha256(f['market']['resolution_rules'].encode()).hexdigest()):
        raise ValueError('exact_new_weather_original_contract_required')
    source_end=at(parse_qs(urlsplit(c['source_url']).query)['date'][0])
    url=weather.ORIGIN+weather.PATH+'?'+urlencode({'ids':c['station'],'format':'json','date':source_end.strftime('%Y-%m-%dT%H:%M:%SZ'),'hours':30})
    return c,source_end,url


async def verify_weather_event(f,*,directory,clock):
    try:
        c,source_end,url=_mapping(f)
        if at(clock())<source_end:return {'status':'pending','event_result_verified':False,'reason':'complete_exact_AWC_reference_window_not_available',**AUTHORITY}
        root=_root(directory)
        if shutil.disk_usage(root).free<100*1024**3+2*MAX_BYTES:raise ValueError('weather_reference_filesystem_reserve')
        namespace='weather-reference-'+digest([c['station'],c['day'],url])[:24];sub=_root(root/namespace)
        async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:raw,item=await _fetch(client,url,clock)
        official=await asyncio.to_thread(parse_station_result,c,raw,observed_at=item['retrieved_at'],source_end=source_end)
        ref=await asyncio.to_thread(_save,sub,raw,item)
        return {'status':'official_event_verified','event_result_verified':True,'verification_protocol':PROTOCOL,
            **{k:f[k] for k in ('id','event_id','market_id','token_id','rules_sha256')},'forecast_id':f['id'],'original_forecast_sha256':digest(f),'available_at':at(clock()).isoformat(),
            'official_result':official,'official_evidence':[ref],'evidence_directory':namespace,'event_group_id':digest(['AWC-station-local-day',c['station'],c['day']]),'target':TARGET,**AUTHORITY}
    except (ValueError,TypeError,KeyError,OSError,httpx.HTTPError) as error:
        return {'status':'withheld','event_result_verified':False,'reason':type(error).__name__+':'+str(error)[:180],**AUTHORITY}


def replay_weather_event(result,study,f,*,evidence_root,as_of):
    now=at(as_of);c,source_end,url=_mapping(f);end=at(c['period_end'])
    if (result.get('verification_protocol')!=PROTOCOL or result.get('event_result_verified') is not True or result.get('target')!=TARGET
        or any(result.get(k)!=v for k,v in AUTHORITY.items()) or result.get('forecast_id')!=f['id'] or result.get('original_forecast_sha256')!=digest(f)
        or any(result.get(k)!=f[k] for k in ('event_id','market_id','token_id','rules_sha256'))
        or sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study.get('forecasts',[]))!=1
        or not at(f['timestamp'])<=at(study['available_at'])<at(c['period_start'])<end<=source_end<=at(result['available_at'])<=now):raise ValueError('exact_prospective_world_weather_proof_required')
    if weather.replay(f,study['evidence'],as_of=now).get('verified') is not True:raise ValueError('original_world_weather_model_replay_required')
    root=Path(evidence_root).absolute();namespace='weather-reference-'+digest([c['station'],c['day'],url])[:24]
    if result['evidence_directory']!=namespace or root.is_symlink() or any(p.is_symlink() for p in root.parents):raise ValueError('weather_reference_directory_mismatch')
    sub=root/namespace;refs=result['official_evidence']
    if sub.is_symlink() or not isinstance(refs,list) or len(refs)!=1:raise ValueError('one_exact_world_weather_reference_required')
    ref=refs[0];expected=ref['content_sha256']+'.json';path=sub/expected
    if (not re.fullmatch(r'[a-f0-9]{64}\.json',expected) or ref['raw_file']!=expected or path.is_symlink()
        or not path.resolve().is_relative_to(sub.resolve()) or not 0<path.stat().st_size<=MAX_BYTES):raise ValueError('weather_reference_path_or_size_invalid')
    raw=path.read_bytes()
    if (len(raw)!=ref['bytes'] or hashlib.sha256(raw).hexdigest()!=ref['content_sha256'] or ref['source_url']!=url
        or not source_end<=at(ref['retrieved_at'])<=at(result['available_at'])<=now):raise ValueError('weather_reference_source_hash_mismatch')
    final=parse_station_result(c,raw,observed_at=ref['retrieved_at'],source_end=source_end)
    if final!=result['official_result'] or result['event_group_id']!=digest(['AWC-station-local-day',c['station'],c['day']]):raise ValueError('weather_reference_event_result_mismatch')
    p=f['probability'];y=final['outcome'];likelihood=p if y else 1-p
    if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('finite_original_weather_probability_required')
    return {'event_result_verified':True,'verification_protocol':PROTOCOL,'forecast_id':f['id'],'event_group_id':result['event_group_id'],
        **{k:f[k] for k in ('event_id','market_id','token_id')},'outcome':y,'available_at':result['available_at'],'resolution_value':final['resolution_value'],
        'brier':(p-y)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,'log_loss_status':'finite' if likelihood>0 else 'positive_infinity',
        'market_brier':None,'market_log_loss':None,'score_scope':'conditional official station-day reference; no native payout or market superiority',
        'official_evidence_sha256':digest(refs),'proof_sha256':digest({k:v for k,v in result.items() if k!='descriptive_score'}),**AUTHORITY}


class WorldWeatherOutcomeStudy(DomainOutcomeStudy):
    """New official-reference result namespace; never a native settlement label."""


class ScopedStore:
    def __init__(self,store):self.underlying=store
    def latest(self,kind,limit=100):return latest(self.underlying,'WorldWeatherOutcomeStudy',limit=limit) if kind=='DomainOutcomeStudy' else []
    def get(self,identity):return self.underlying.get(identity)
    def append(self,record):
        if not isinstance(record,DomainOutcomeStudy):raise TypeError('world weather outcomes reject unrelated record')
        return self.underlying.append(WorldWeatherOutcomeStudy.model_validate(record.model_dump()).model_copy(update={'source':'neraium-poly/world-weather-outcome/v35'}))


def _original(store,identity):
    value=store.get(identity)
    if value is None:raise ValueError('immutable_world_weather_original_missing')
    if isinstance(value,dict):return value
    if hashlib.sha256(value[1].encode()).hexdigest()!=value[2]:raise ValueError('immutable_world_weather_original_hash_mismatch')
    return json.loads(value[1])


class WorldWeatherOutcomes(DomainOutcomes):
    def __init__(self,store,directory,**kwargs):
        super().__init__(ScopedStore(store),directory,**kwargs);self.lock=asyncio.Lock()
        self.policy_sha=digest(Path(__file__).read_text())
        if self.state.get('policy_sha256',self.policy_sha)!=self.policy_sha:raise ValueError('world_weather_outcome_policy_mismatch_no_reset')
        self.state['policy_sha256']=self.policy_sha

    def _due(self,p,now):return at(p['end'])<=now

    async def step(self):
        if self.lock.locked():return False
        async with self.lock:return await self._step()

    async def _step(self):
        now=at(self.clock())
        if not self.can_write() or self.state['last_at'] and (now-at(self.state['last_at'])).total_seconds()<300:return False
        s=deepcopy(self.state);rows=latest(self.store.underlying,KIND,limit=256);head=s['source_heads'].get(KIND)
        if head and head not in {r['id'] for r in rows} or not head and rows and int(rows[-1]['id'].split(':',1)[0])!=1:raise ValueError('world_weather_source_head_gap_requires_verified_readonly_backfill')
        for study in rows:
            for f in study.get('forecasts',[]):
                if f['id'] in s['verified']:continue
                _c,end,_url=_mapping(f)
                if len(s['pending'])+len(s['verified'])>=8192 and f['id'] not in s['pending']:raise ValueError('world_weather_outcome_capacity_reached')
                s['pending'][f['id']]={'study_id':study['id'],'study_sha256':digest(study),'forecast_sha256':digest(f),'kind':KIND,'adapter':'weather','end':end.isoformat()}
        if rows:s['source_heads'][KIND]=rows[0]['id']
        self._commit(s,'index');due=[(fid,p) for fid,p in s['pending'].items() if self._due(p,now)]
        checked=0
        for fid,p in sorted(due,key=lambda x:s['checked'].get(x[0],''))[:2]:
            if not self.can_write():return bool(checked)
            s=deepcopy(self.state);study=_original(self.store,p['study_id']);f=next(f for f in study['forecasts'] if f['id']==fid)
            if digest(study)!=p['study_sha256'] or digest(f)!=p['forecast_sha256']:raise ValueError('world_weather_original_binding_changed')
            try:
                result=await verify_weather_event(f,directory=self.directory,clock=self.clock)
                if result.get('event_result_verified'):
                    score=await asyncio.to_thread(replay_weather_event,result,study,f,evidence_root=self.directory,as_of=at(self.clock()))
                    result={**result,'descriptive_score':score}
                    s['verified'][fid]={'model_id':f['model_id'],'event_id':f['event_id'],'event_group_id':score['event_group_id']};s['pending'].pop(fid,None)
                else:s['last_reasons']['weather']=result.get('reason','official_reference_unverified')
            except Exception as error:  # noqa: BLE001 - source/replay errors cannot create labels
                result={'status':'withheld','event_result_verified':False,'reason':type(error).__name__+':'+str(error)[:160],**AUTHORITY};s['last_reasons']['weather']=result['reason']
            s['checks']+=1;s['checked'][fid]=at(self.clock()).isoformat();self._commit(s,'outcome_check',original_study_id=study['id'],original_study_sha256=digest(study),original_kind=KIND,forecast_id=fid,adapter='weather',result=result);checked+=1
        return bool(checked)

    def status(self):
        result=super().status();result.update(independent_event_count=len({v['event_group_id'] for v in self.state['verified'].values()}),native_payout_verified=False,market_baseline_comparable=False,score_scope='conditional official-reference descriptive results only')
        return result
