"""Causal input scheduling and bounded sampling beside the unchanged model engine."""
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase25.continuous import modules
from neraium_poly.research.phase26.books import SupplementalBooks


class ResearchInputPolicy(Record):
    policy:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False


class ResearchInputObservation(Record):
    source_frame_id:str|None=None
    book:dict|None=None
    counts:dict=Field(default_factory=dict)
    reasons:dict=Field(default_factory=dict)
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False


class Inputs:
    def __init__(self,store,*,clock,can_write,watcher=None):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.counts=Counter();self.last_sample={};self.last_global=None;self.last_preflight=None;self.rejections={}
        policy={'version':'phase26-causal-inputs-v1','code_sha256':digest([Path(__file__).read_text(),Path(__file__).with_name('books.py').read_text()]),
                'native_book_max_age_seconds':15,'max_spread':.05,'model_interval_seconds':300,
                'record_sampling':'qualified books at most one/token/60seconds and one/second globally; selected books also preserved in forecasts',
                'sports_check_after_start_hours':1,'finality_checks_relaxed':False,'primary_collection_duplicated':False,'max_supplemental_tokens':32}
        identity=digest(['research-input-policy',policy]);existing=store.get(identity)
        if existing is None:
            if not self.can_write():raise ValueError('research input policy archive unavailable')
            now=at(clock());store.append(ResearchInputPolicy(id=identity,timestamp=now,available_at=now,source='neraium-poly/research-inputs/v26',policy=policy))
        if existing is not None:
            value=existing if isinstance(existing,dict) else json.loads(existing[1])
            if value.get("policy")!=policy:raise ValueError("research input policy binding mismatch")
        self.policy_id=identity
        self.watcher=watcher or SupplementalBooks(clock=clock,on_book=self.on_book)

    async def on_book(self,book):
        self.counts['qualified_callbacks']+=1;now=at(self.clock())
        if (self.last_global and now-self.last_global<timedelta(seconds=1)
            or book.token_id in self.last_sample and now-self.last_sample[book.token_id]<timedelta(seconds=60)):
            self.counts['sampling_skips']+=1;return
        if not self.can_write():self.counts['archive_backpressure']+=1;return
        raw=book.model_dump(mode='json')
        if len(str(raw).encode())>256*1024:self.counts['payload_budget_rejections']+=1;return
        if book.source not in PUBLIC_BOOK_SOURCES or not assess_book(book,now,max_spread=.05).healthy:
            self.counts['callback_quality_rejections']+=1;return
        self.store.append(ResearchInputObservation(id=digest(['supplemental-native-sample',raw]),timestamp=book.timestamp,available_at=book.available_at,
            source=book.source,book=raw,counts={'sampled':1}))
        self.last_global=now;self.last_sample[book.token_id]=now
        self.last_sample=dict(list(self.last_sample.items())[-64:]);self.counts['archived_samples']+=1

    async def prepare(self,frame,*,base_tokens,wait=False):
        raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
        now=at(self.clock());selected=[];adapters=modules()
        for value in raw['markets']:
            if value['token_id'] in base_tokens:continue
            if any(adapters[name].supports(value,cutoff=now).get('supported') for name in ('finance','economics')):selected.append(value)
        await self.watcher.update(selected)
        if wait and selected:await self.watcher.wait_fresh(timeout=20)
        return self.qualify(frame,adapters=adapters)

    def qualify(self,frame,*,adapters=None):
        raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else dict(frame)
        now=at(self.clock());adapters=adapters or modules();books={b['token_id']:OrderBookSnapshot.model_validate(b) for b in raw['books']}
        books.update({b.token_id:b for b in self.watcher.snapshot()})
        markets=[];reasons=Counter();considered=0;kept=0
        for m in raw['markets']:
            supported=any(adapters[n].supports(m,cutoff=now).get('supported') for n in ('finance','economics'))
            if supported:
                considered+=1;b=books.get(m['token_id'])
                found=('no_current_qualified_book',) if b is None else assess_book(b,now,max_spread=.05,expected_token=m['token_id']).reasons
                if b is not None and (b.market_id!=m['market_id'] or b.source not in PUBLIC_BOOK_SOURCES):found=('public_book_identity_mismatch',)
                if found:reasons.update(found);continue
                kept+=1
            markets.append(m)
        tokens={m['token_id'] for m in markets};accepted=[b.model_dump(mode='json') for t,b in books.items() if t in tokens]
        self.rejections=dict(reasons);self.last_preflight=now.isoformat();self.counts['preflights']+=1
        self.counts['supported_token_observations']+=considered;self.counts['qualified_token_observations']+=kept
        if self.can_write():
            self.store.append(ResearchInputObservation(id=digest(['input-preflight',raw['id'],now.isoformat(),considered,kept,reasons]),timestamp=now,available_at=now,
                source='neraium-poly/research-inputs/v26',source_frame_id=raw['id'],counts={'considered':considered,'qualified':kept,'withheld':considered-kept},reasons=dict(reasons)))
        return SharedMarketFrame.model_validate({**raw,'id':digest([raw['id'],self.policy_id,now.isoformat(),accepted]),
            'timestamp':now.isoformat(),'available_at':now.isoformat(),'markets':markets,'books':accepted})

    def status(self):
        return {'watcher':self.watcher.status(),'counts':dict(self.counts),'last_preflight':self.last_preflight,'preflight_rejections':self.rejections,
                'policy_id':self.policy_id,'counter_scope':'process-local sampling/transport; durable observation records retained','scope':'sampled supplementary books and filtered research inputs; native source times and original model gates unchanged','trading_authority':False}
    async def close(self):await self.watcher.close()
