"""Domain adapters in the existing research archive; never an order-admission path."""

import asyncio
import hashlib
import importlib
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.data.polymarket import PolymarketAdapter
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from pydantic import Field

ADAPTERS=('weather','economics','finance','sports')


class DomainResearchStudy(Record):
    operation: Literal['enrollment','forecast_batch','scan']
    enrollment_id: str
    enrollment: list[dict] = Field(default_factory=list)
    source_frame_id: str | None = None
    forecasts: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    observations: list[dict] = Field(default_factory=list)
    rejections: dict = Field(default_factory=dict)
    checkpoint: dict
    checkpoint_sha256: str
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


def at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('aware domain time required')
    return value.astimezone(UTC)


def horizon(seconds):
    if seconds<=0:raise ValueError('future domain event required')
    return next((label for n,label in [(8*3600,'0-8h'),(86400,'8-24h'),(7*86400,'1-7d'),(31*86400,'7-31d')] if seconds<=n),'over31d')


class DomainResearch:
    def __init__(self,store,*,clock=None,can_write=None,adapters=None,interval=300,book_provider=None):
        if not 300<=interval<=3600:raise ValueError('bounded domain source interval required')
        self.store,self.clock=store,clock or (lambda:datetime.now(UTC));self.can_write=can_write or (lambda:True)
        self.adapters=adapters if adapters is not None else {n:importlib.import_module(f'neraium_poly.research.phase24.{n}') for n in ADAPTERS}
        self.interval,self.book_provider=interval,book_provider or self._book
        self.lock=asyncio.Lock();self.last_error=None
        self.definitions=[{**d,'adapter':name} for name,mod in self.adapters.items() for d in mod.definitions()]
        if len({d['model_id'] for d in self.definitions})!=len(self.definitions):raise ValueError('unique domain model IDs required')
        self.code_sha=hashlib.sha256(Path(__file__).read_bytes()+b''.join(Path(mod.__file__).read_bytes() for mod in self.adapters.values() if getattr(mod,'__file__',None))).hexdigest()
        self.enrollment_id=digest(['phase23-prospective-research',self.definitions,self.code_sha])
        self.state={'version':'phase24-domain-v1','code_sha256':self.code_sha,'enrollment_id':self.enrollment_id,'enrolled':False,
            'last_at':None,'last_attempt_at':None,'scans':0,'forecasts':0,'parents':[],'seen':[], 'parent_models':[], 'attempts':{},'candidate_attempts':{},'rejections':{},'latest':[],
            'sequence':0,'enrollment_record_id':None,'models':{d['model_id']:{'forecasts':0,'resolved':0,'brier':None,'log_loss':None} for d in self.definitions}}
        rows=store.latest('DomainResearchStudy',limit=1)
        if rows:
            row=DomainResearchStudy.model_validate(rows[0]);s=unpack_checkpoint(row.checkpoint)
            if (digest(s)!=row.checkpoint_sha256 or s.get('code_sha256')!=self.code_sha or s.get('enrollment_id')!=self.enrollment_id
                or s.get('last_at')!=row.available_at.isoformat() or len(s.get('seen',[]))>8192):
                raise ValueError('domain checkpoint/model policy mismatch; no reset')
            self.state=s

    async def _book(self,m):
        adapter=PolymarketAdapter(retries=2,min_interval=.25,clock=self.clock)
        try:return await adapter.book(m.market_id,m.token_id)
        finally:await adapter.close()

    def _commit(self,s,operation,*,forecasts=(),evidence=(),frame_id=None,rejections=None,observations=()):
        now=at(self.clock())
        if s['last_at'] and now<at(s['last_at']):raise ValueError('domain clock regression; no backdated record')
        s['last_at']=now.isoformat();s['sequence']+=1
        record_id=digest([self.enrollment_id,'enrollment']) if operation=='enrollment' else digest([self.enrollment_id,operation,s,forecasts,evidence])
        record_id=f"{s['sequence']:012d}:"+record_id
        if operation=='enrollment':s['enrollment_record_id']=record_id
        row=DomainResearchStudy(id=record_id,timestamp=now,available_at=now,
            source='neraium-poly/domain-research/v24',operation=operation,enrollment_id=self.enrollment_id,
            enrollment=self.definitions if operation=='enrollment' else [],source_frame_id=frame_id,
            forecasts=list(forecasts),evidence=list(evidence),observations=list(observations),rejections=rejections or {},checkpoint=pack_checkpoint(s),checkpoint_sha256=digest(s))
        if not self.can_write():raise ValueError('domain_archive_backpressure')
        self.store.append(row);self.state=s

    def _validate(self,f,evidence,m,book,*,ended,adapter):
        f=deepcopy(f);f.setdefault('market',m.model_dump(mode='json'));f.setdefault('book',book.model_dump(mode='json'))
        mm=MarketSnapshot.model_validate(f['market']);bb=OrderBookSnapshot.model_validate(f['book']);created=at(f['timestamp']);cutoff=at(f['evidence_cutoff'])
        if (any(f[k]!=getattr(m,k) for k in ('event_id','market_id','token_id')) or digest(mm.model_dump(mode='json'))!=digest(m.model_dump(mode='json'))
            or not mm.timestamp<=mm.available_at<=cutoff<=created<=ended or mm.market_id!=m.market_id or mm.token_id!=m.token_id
            or mm.event_id!=m.event_id or mm.resolution_rules!=m.resolution_rules or mm.end_time!=m.end_time
            or mm.exchange!='polymarket' or mm.source!='https://gamma-api.polymarket.com' or mm.status!='active'
            or bb.exchange!=mm.exchange
            or bb.market_id!=m.market_id or bb.source not in PUBLIC_BOOK_SOURCES
            or not assess_book(bb,created,max_spread=.05,expected_token=m.token_id).healthy
            or not assess_book(bb,ended,max_spread=.05,expected_token=m.token_id).healthy
            or not m.end_time or ended>=m.end_time or ended>=at(f['event_end_time'])):
            raise ValueError('causal_fresh_domain_market_book_identity_required')
        model=next((x for x in self.definitions if x['model_id']==f.get('model_id')),None)
        if not model or model['adapter']!=adapter or f['model_sha256']!=model['model_sha256'] or f['rules_sha256']!=hashlib.sha256(m.resolution_rules.encode()).hexdigest():
            raise ValueError('declared_model_and_exact_rules_required')
        if (f.get('research_only') is not True or f.get('trading_authority') is not False or f.get('certification_authority') is not False
            or not 0<=f['lower_probability']<=f['probability']<=f['upper_probability']<=1):
            raise ValueError('research_only_bounded_domain_probability_required')
        byid={e.id:e for e in evidence};ids=f['evidence_ids']
        if len(byid)!=len(evidence):raise ValueError('duplicate domain evidence identity')
        if not ids or len(ids)!=len(set(ids)) or any(x not in byid for x in ids):raise ValueError('bound_domain_evidence_required')
        selected=[byid[x] for x in ids]
        for e in selected:
            if (urlsplit(e.source).scheme!='https' or not urlsplit(e.source).hostname
                or urlsplit(e.source).hostname=='polymarket.com' or urlsplit(e.source).hostname.endswith('.polymarket.com')
                or not e.independent_of_polymarket or e.qualification!='qualified_research' or digest(e.payload)!=e.content_sha256
                or max(e.timestamp,e.available_at,e.retrieved_at)>cutoff):raise ValueError('qualified_causal_external_payload_required')
        f['evidence_lineages']=sorted({e.provider+':'+e.source_id for e in selected})
        if not f.get('source_lineages'):raise ValueError('declared model source lineage required')
        f['book_sha256']=digest(bb.model_dump(mode='json'));f['book_id']=bb.id
        midpoint=(bb.bids[0].price+bb.asks[0].price)/2
        if f.get('unconditional_contract_probability') is False or f.get('target_conditioning'):
            f['market_probability']=None;f['market_expected_payout']=midpoint
            f['market_baseline_comparable']=False
        elif abs(f.get('market_probability',midpoint)-midpoint)>1e-12:raise ValueError('same_native_quote_baseline_required')
        else:f['market_probability']=midpoint;f['market_baseline_comparable']=True
        f['adapter']=model['adapter'];f['enrollment_id']=self.enrollment_id;f['reviewed_dependency_group']=None;f['independence_reviewed']=False
        f['horizon_bucket']=horizon((at(f['event_end_time'])-created).total_seconds())
        f['id']=digest([self.enrollment_id,f['model_id'],m.event_id,m.market_id,m.token_id,f['horizon_bucket']])
        return f

    async def step(self,frame):
        if self.lock.locked():return False
        async with self.lock:
            now=at(self.clock())
            if not self.can_write() or self.state['last_attempt_at'] and (now-at(self.state['last_attempt_at'])).total_seconds()<self.interval:return False
            raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
            if (not isinstance(raw,dict) or raw.get('producer_health',{}).get('status')!='ok'
                or len(raw.get('markets',[]))>4000 or len(raw.get('books',[]))>4000 or at(raw['available_at'])>now):return False
            if not self.state['enrolled']:
                s=deepcopy(self.state);s['enrolled']=True;self._commit(s,'enrollment')
            if len({m['token_id'] for m in raw['markets']})!=len(raw['markets']) or len({b['token_id'] for b in raw['books']})!=len(raw['books']):
                raise ValueError('unique domain market/token observations required')
            bytoken={b['token_id']:OrderBookSnapshot.model_validate(b) for b in raw['books']};groups=defaultdict(list);rejections=Counter()
            for value in raw['markets']:
                m=MarketSnapshot.model_validate(value)
                for name,mod in self.adapters.items():
                    support=mod.supports(m,cutoff=now)
                    if not support.get('supported'):
                        for reason in support.get('reasons',[]):rejections[name+':'+str(reason)[:120]]+=1
                        continue
                    b=bytoken.get(m.token_id);score=sum(x.price*x.size for x in b.asks[:3]) if b else 0
                    bucket=horizon((m.end_time-now).total_seconds()) if m.end_time else None
                    definitions=[d for d in self.definitions if d['adapter']==name]
                    if definitions and all(digest([self.enrollment_id,d['model_id'],m.event_id,bucket]) in self.state['parent_models'] for d in definitions):continue
                    candidate=f'{name}|{m.market_id}|{m.token_id}'
                    groups[(name,m.event_id)].append((self.state['candidate_attempts'].get(candidate,0),abs(m.probability-.5),-score,m.market_id,m.token_id,m,b))
            selected=[]
            for name in self.adapters:
                keys=[k for k in groups if k[0]==name]
                for key in sorted(keys,key=lambda k:(self.state['attempts'].get('|'.join(k),0),min(groups[k])[:5]))[:2]:
                    selected.append((key,min(groups[key])[-2:]))
            s=deepcopy(self.state);s['last_attempt_at']=now.isoformat();s['scans']+=1
            for key,(m,_b) in selected:
                k='|'.join(key);s['attempts'][k]=s['attempts'].get(k,0)+1
                candidate='|'.join((key[0],m.market_id,m.token_id));s['candidate_attempts'][candidate]=s['candidate_attempts'].get(candidate,0)+1
            s['attempts']=dict(list(s['attempts'].items())[-4096:]);s['candidate_attempts']=dict(list(s['candidate_attempts'].items())[-4096:])
            total=Counter(s['rejections']);total.update(rejections);s['rejections']=dict(total.most_common(128));self._commit(s,'scan',frame_id=raw['id'],rejections=dict(rejections))
            gate=asyncio.Semaphore(2)
            async def run(item):
                key,(m,b)=item
                async with gate:
                    try:
                        if b is None or not assess_book(b,at(self.clock()),max_spread=.05,expected_token=m.token_id).healthy:b=await self.book_provider(m)
                        result=await self.adapters[key[0]].forecast(m,b,clock=self.clock)
                        return key,m,b,result,None
                    except Exception as error: # noqa: BLE001 - unavailable sources cannot produce forecasts
                        return key,m,b,None,f'{type(error).__name__}:{str(error)[:160]}'
            jobs=[asyncio.create_task(run(item)) for item in selected];count=0
            try:
                for ready in asyncio.as_completed(jobs):
                    key,m,b,result,error=await ready;s=deepcopy(self.state);reason=Counter();forecasts=[];evidence=[]
                    try:
                        if error:raise ValueError(error)
                        unique={}
                        for e in result.get('evidence',[]):
                            e=DomainEvidence.model_validate(e.model_dump() if isinstance(e,DomainEvidence) else e)
                            if e.id in unique and digest(unique[e.id].model_dump(mode='json'))!=digest(e.model_dump(mode='json')):
                                raise ValueError('conflicting duplicate domain evidence ID')
                            unique[e.id]=e
                        evidence=list(unique.values())
                        for f in result.get('forecasts',[]):
                            f=self._validate(f,evidence,m,b,ended=at(self.clock()),adapter=key[0])
                            parent_key=digest([self.enrollment_id,f['model_id'],f['event_id'],f['horizon_bucket']])
                            if f['id'] in s['seen'] or parent_key in s['parent_models']:continue
                            if len(s['seen'])>=8192:raise ValueError('domain_enrollment_capacity_reached')
                            forecasts.append(f);s['seen'].append(f['id']);s['parent_models'].append(parent_key);s['forecasts']+=1;s['models'][f['model_id']]['forecasts']+=1
                            if f['event_id'] not in s['parents']:s['parents'].append(f['event_id'])
                        reason.update(str(x)[:160] for x in result.get('rejections',[]))
                    except (ValueError,TypeError,KeyError,OverflowError) as exc:reason[str(exc)[:160]]+=1
                    counters=Counter(s['rejections']);counters.update(reason);s['rejections']=dict(counters.most_common(128))
                    s['latest']=[{k:f.get(k) for k in ['id','domain','model_id','event_id','probability','timestamp','target_conditioning']} for f in forecasts][-32:]
                    self._commit(s,'forecast_batch' if forecasts else 'scan',forecasts=forecasts,evidence=[e.model_dump(mode='json') for e in evidence],frame_id=raw['id'],rejections=dict(reason),observations=[{'adapter':key[0],'market':m.model_dump(mode='json'),'input_book_id':b.id if b is not None else None,'input_book_sha256':digest(b.model_dump(mode='json')) if b is not None else None,'reasons':dict(reason),'accepted_forecast_ids':[f['id'] for f in forecasts],'priority_scope':'parent diversification, candidate retry and quote uncertainty/depth; not an independent probability feature'}]);count+=len(forecasts)
            finally:
                for job in jobs:
                    if not job.done():job.cancel()
                await asyncio.gather(*jobs,return_exceptions=True)
            self.last_error=None
            return count>0

    def status(self):
        s=self.state
        return {'status':'research_only','last_evaluation_at':s['last_at'],'scans':s['scans'],'forecasts':s['forecasts'],'pending_forecasts':s['forecasts'],
            'native_parents':len(s['parents']),'models':deepcopy(s['models']),'latest':deepcopy(s['latest']),
            'rejections':dict(s['rejections']),'enrollment_id':self.enrollment_id,'source_workers':2,
            'calibration_status':'unvalidated_research','certification_authority':False,'trading_authority':False,
            'selection_policy':'unseen parent/model/horizon before repeat thresholds; source liquidity and quote uncertainty select research targets, never independent model features',
            'counter_scope':'durable domain registry only; native parents are not reviewed independent events'}
