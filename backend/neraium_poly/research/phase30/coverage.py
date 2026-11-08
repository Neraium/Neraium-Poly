"""Targeted current weather metadata acquisition; no probability or authority."""
from collections import Counter, defaultdict

from neraium_poly.research.phase25 import finance, weather
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
