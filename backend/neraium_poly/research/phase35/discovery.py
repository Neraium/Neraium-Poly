"""Bounded genuine weather metadata supplementation; never invent native books."""
import asyncio
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase25.dependencies import at

from . import weather

IDENTITY=('market_id','event_id','question','resolution_rules','resolution_source','outcome','end_time','tick_size','min_order_size')


class WorldWeatherDiscoveryStudy(Record):
    discovery_policy_sha256: str
    source_frame_id: str
    source_frame_sha256: str
    markets: list[dict] = Field(default_factory=list)
    rejections: dict = Field(default_factory=dict)
    refresh_sequence: int
    canonical_station_days: list[str] = Field(default_factory=list)
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False


class WorldWeatherUniverse:
    def __init__(self,store,*,clock,can_write):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.policy_sha=digest(Path(__file__).read_text());self.last=None;self.cached=[];self.added=[];self.rejections={};self.sequence=0;self.groups=[];self.lock=asyncio.Lock()
        rows=latest(store,'WorldWeatherDiscoveryStudy',limit=1)
        if rows:
            row=WorldWeatherDiscoveryStudy.model_validate(rows[0])
            if row.discovery_policy_sha256!=self.policy_sha or len(row.markets)>100:raise ValueError('world_weather_discovery_policy_mismatch_no_reset')
            self.cached=row.markets;self.last=row.available_at;self.sequence=row.refresh_sequence;self.groups=row.canonical_station_days;self.rejections=row.rejections

    async def frame(self,frame):
        async with self.lock:
            return await self._frame(frame)

    async def _frame(self,frame):
        raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else dict(frame);now=at(self.clock())
        if raw.get('producer_health',{}).get('status')!='ok' or at(raw['available_at'])>now:return frame
        if len(raw.get('markets',[]))>4000 or len(raw.get('books',[]))>4000:raise ValueError('bounded_world_weather_source_frame_required')
        if self.last is None or now-self.last>=timedelta(minutes=15):
            if not self.can_write():return frame
            rejected=Counter();accepted={};groups=defaultdict(list)
            try:
                values=await weather.discover(clock=self.clock)
                if not isinstance(values,(tuple,list)) or len(values)>3000:raise ValueError('bounded_public_weather_discovery_required')
            except Exception as error:  # noqa: BLE001 - source outages never produce observations
                values=[];rejected['source:'+type(error).__name__+':'+str(error)[:120]]+=1
            finished=at(self.clock());books={b['token_id']:b for b in raw['books']}
            for value in values:
                m=MarketSnapshot.model_validate(value.model_dump() if hasattr(value,'model_dump') else value);mapped=weather.supports(m,cutoff=finished)
                if not mapped['supported']:rejected.update(mapped['reasons']);continue
                body=m.model_dump(mode='json');old=accepted.get(m.token_id)
                if old is not None:
                    if any(old[k]!=body[k] for k in IDENTITY):raise ValueError('world_weather_token_identity_conflict')
                    continue
                accepted[m.token_id]=body;c=mapped['contract'];canonical=f"weather:{c['station']}:{c['day']}";healthy=False
                if m.token_id in books:
                    b=OrderBookSnapshot.model_validate(books[m.token_id]);healthy=b.market_id==m.market_id and assess_book(b,finished,max_spread=.05,expected_token=m.token_id).healthy
                groups[(canonical,m.event_id)].append((not healthy,abs(m.probability-.5),m.token_id,body))
            keys=sorted(groups);keys=keys[self.sequence%len(keys):]+keys[:self.sequence%len(keys)] if keys else [];queues=[];selected=[]
            for key in keys:
                ordered=sorted(groups[key]);fresh=[v for v in ordered if not v[0]];other=[v for v in ordered if v[0]]
                shift=(self.sequence*max(1,100//len(keys)))%len(other) if other else 0
                queues.append(iter(fresh+other[shift:]+other[:shift]))
            while queues and len(selected)<100:
                pending=[]
                for queue in queues:
                    try:selected.append(next(queue)[-1]);pending.append(queue)
                    except StopIteration:continue
                    if len(selected)==100:break
                queues=pending
            row=WorldWeatherDiscoveryStudy(id=digest(['world-weather-discovery-v35',finished.isoformat(),raw['id'],selected,rejected,self.sequence+1]),timestamp=finished,available_at=finished,source='https://gamma-api.polymarket.com',
                discovery_policy_sha256=self.policy_sha,source_frame_id=raw['id'],source_frame_sha256=digest(raw),markets=selected,rejections=dict(rejected),refresh_sequence=self.sequence+1,canonical_station_days=sorted({k[0] for k in groups}))
            if not self.can_write():return frame
            self.store.append(row);self.cached=selected;self.last=finished;self.sequence=row.refresh_sequence;self.rejections=dict(rejected);self.groups=row.canonical_station_days
        existing={m['token_id']:m for m in raw['markets']}
        if len(existing)!=len(raw['markets']):raise ValueError('duplicate_world_weather_base_token')
        extras=[];finished=at(self.clock())
        for m in self.cached:
            old=existing.get(m['token_id'])
            if old and any(old[k]!=m[k] for k in IDENTITY):raise ValueError('world_weather_base_identity_conflict')
            if old is None and weather.supports(m,cutoff=finished)['supported']:extras.append(m)
        extras=extras[:4000-len(existing)];self.added=extras
        if not extras:return frame
        return SharedMarketFrame.model_validate({**raw,'id':digest([raw['id'],self.policy_sha,extras]),'timestamp':finished.isoformat(),'available_at':finished.isoformat(),'markets':raw['markets']+extras})

    def status(self):
        return {'last_source_at':self.last.isoformat() if self.last else None,'discovered_outcome_tokens':len(self.cached),'added_outcome_tokens':len(self.added),'canonical_station_days':len(self.groups),'native_parents':len({m['event_id'] for m in self.cached}),
            'counter_scope':'station-day groups deduplicate Gamma parents; not independently verified outcomes','discovery_policy_sha256':self.policy_sha,'errors':dict(self.rejections),'research_only':True,'trading_authority':False}
