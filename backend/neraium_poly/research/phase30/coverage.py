"""Targeted current weather metadata acquisition; no probability or authority."""
import asyncio
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from pydantic import Field

from neraium_poly.contracts import MarketSnapshot, Record
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import finance, weather
from neraium_poly.research.phase25.continuous import modules
from neraium_poly.research.phase25.dependencies import at

WEATHER_QUERIES=('highest temperature in Chongqing','highest temperature in Qingdao','highest temperature in Chengdu')


async def discover_weather(*, clock, search=None, maximum=64):
    """Close the missing discovery route for an existing exact-station model.

    Existing public Gamma acquisition enforces response/query bounds. Results
    still must pass the unchanged source, station, window and rules interpreter.
    Parent-round-robin selection retains diverse days/locations within64tokens;
    native books and external weather evidence remain independently mandatory.
    """
    if type(maximum) is not int or not 1<=maximum<=64:raise ValueError('bounded_weather_discovery_required')
    search=search or finance._discover
    rows=await search(WEATHER_QUERIES,clock=clock)
    if not isinstance(rows,(tuple,list)) or len(rows)>3000:raise ValueError('bounded_public_weather_metadata_required')
    now=at(clock());groups=defaultdict(list);seen={};rejections=Counter()
    for m in rows:
        raw=m.model_dump(mode='json') if hasattr(m,'model_dump') else m
        mapped=weather.supports(raw,cutoff=now)
        if not mapped.get('supported'):
            rejections.update(mapped.get('reasons',('unsupported_exact_weather_contract',)));continue
        token=raw['token_id'];identity=tuple(str(raw.get(k)) for k in ('market_id','event_id','question','outcome','resolution_rules','resolution_source','end_time','tick_size','min_order_size'))
        if token in seen:
            if seen[token]!=identity:raise ValueError('ambiguous_public_weather_token_identity')
            continue
        seen[token]=identity;groups[(at(raw['end_time']),raw['event_id'])].append(m)
    queues=[]
    for key,values in sorted(groups.items()):
        values.sort(key=lambda x:(str(x.market_id),x.outcome) if hasattr(x,'market_id') else (str(x['market_id']),x['outcome']))
        queues.append(iter(values))
    accepted=[]
    while queues and len(accepted)<maximum:
        pending=[]
        for values in queues:
            try:value=next(values)
            except StopIteration:continue
            accepted.append(value);pending.append(values)
            if len(accepted)==maximum:break
        queues=pending
    return accepted


class WeatherDiscoveryStudy(Record):
    discovery_policy_sha256: str
    markets: list[dict] = Field(default_factory=list)
    rejections: dict = Field(default_factory=dict)
    research_only: bool = True
    trading_authority: bool = False


class WeatherUniverse:
    def __init__(self,store,*,clock,can_write):
        self.store,self.clock,self.can_write=store,clock,can_write;self.last=None;self.cached=[];self.rejections={};self.added=[]
        self.policy_sha=digest(Path(__file__).read_text())
    async def frame(self,frame):
        now=at(self.clock());raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else dict(frame)
        if raw.get('producer_health',{}).get('status')!='ok':return frame
        if self.last is None or now-self.last>=timedelta(minutes=15):
            if not self.can_write():return frame
            values=[];rejected={};gate=asyncio.Semaphore(2)
            async def one(name,mod):
                async with gate:
                    discover=getattr(mod,'discover',None)
                    if discover is None and name=='weather':
                        discover=discover_weather
                    if discover is None:return []
                    try:
                        result=await discover(clock=self.clock)
                        if not isinstance(result,(tuple,list)) or len(result)>100:raise ValueError('bounded actual discovery required')
                        return list(result)
                    except Exception as error: # noqa: BLE001 - missing sources do not create markets
                        rejected[name]=f'{type(error).__name__}:{str(error)[:160]}';return []
            for result in await asyncio.gather(*(one(name,mod) for name,mod in modules().items())):values.extend(result)
            accepted={};finished=at(self.clock())
            for value in values:
                m=MarketSnapshot.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
                if (m.source!='https://gamma-api.polymarket.com' or m.exchange!='polymarket' or m.status!='active'
                    or not m.end_time or m.end_time<=finished or not m.timestamp<=m.available_at<=finished):continue
                if m.token_id in accepted and digest(accepted[m.token_id])!=digest(m.model_dump(mode='json')):raise ValueError('supplemental token conflict')
                accepted[m.token_id]=m.model_dump(mode='json')
            row=WeatherDiscoveryStudy(id=digest(['expansion-discovery',finished.isoformat(),accepted,rejected]),timestamp=finished,available_at=finished,
                source='https://gamma-api.polymarket.com',markets=list(accepted.values()),rejections=rejected,discovery_policy_sha256=self.policy_sha)
            if not self.can_write():return frame
            self.store.append(row);self.cached=list(accepted.values());self.last=finished;self.rejections=rejected
        existing={m['token_id']:m for m in raw['markets']};extras=[]
        for m in self.cached:
            old=existing.get(m['token_id'])
            if old and any(old[k]!=m[k] for k in ('market_id','event_id','question','resolution_rules','resolution_source','outcome','end_time','tick_size','min_order_size')):
                raise ValueError('supplemental/base contract identity conflict')
            if m['token_id'] not in existing and at(m['end_time'])>at(self.clock()):extras.append(m)
        self.added=extras
        if not extras:return frame
        finished=at(self.clock());return SharedMarketFrame.model_validate({**raw,'id':digest([raw['id'],extras]),'timestamp':finished.isoformat(),
            'available_at':finished.isoformat(),'markets':raw['markets']+extras})

    def status(self):
        return {'last_source_at':self.last.isoformat() if self.last else None,'discovered_market_ids':len({m['market_id'] for m in self.cached}),
                'added_market_ids':len({m['market_id'] for m in self.added}),'added_outcome_tokens':len(self.added),
                'discovery_policy_sha256':self.policy_sha,'source':'public Gamma metadata; books independently acquired from public CLOB','errors':dict(self.rejections)}
