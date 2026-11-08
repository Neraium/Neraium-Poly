"""Fresh executable weather siblings before blind threshold retries; research only."""
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import weather
from neraium_poly.research.phase25.dependencies import at


class WeatherInputSelection(Record):
    source_frame_id:str
    source_frame_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")
    policy_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")
    selected_frame_id:str
    selected_frame_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")
    deferred_tokens:list[str]=Field(default_factory=list)
    preferred_tokens:list[str]=Field(default_factory=list)
    rejection_counts:dict=Field(default_factory=dict)
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


def prepare_weather_frame(frame, *, as_of):
    """Keep fresh siblings for a supported station-day's next source attempt.

    The frozen model engine chooses a single threshold per parent by retry count
    before quote quality. Supplying all stale siblings can therefore waste that
    parent's bounded source slot even when an exact fresh quote already exists.
    Defer only non-executable siblings of a group with an observed fresh book.
    If no fresh sibling exists retain all metadata for the existing bounded HTTP
    fallback. Other domains and original native observations are unchanged.
    """
    now=at(as_of);raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
    if (not isinstance(raw,dict) or len(raw.get('markets',[]))>4096 or len(raw.get('books',[]))>4096
        or not at(raw['timestamp'])<=at(raw['available_at'])<=now):raise ValueError('bounded_causal_weather_selection_frame_required')
    typed=SharedMarketFrame.model_validate(raw)
    markets={m.token_id:m for m in typed.markets};books={b.token_id:b for b in typed.books}
    if len(markets)!=len(typed.markets) or len(books)!=len(typed.books):raise ValueError('unique_weather_selection_market_and_book_tokens_required')
    groups=defaultdict(list);reasons={};counts=Counter();preferred=[];deferred=[]
    for m in typed.markets:
        support=weather.supports(m,cutoff=now)
        if not support['supported']:continue
        c=support['contract'];group=(m.event_id,c['station'],c['day']);groups[group].append(m.token_id)
        b=books.get(m.token_id);fail=[]
        if b is None:fail=['current_native_book_missing']
        elif b.market_id!=m.market_id or b.exchange!=m.exchange or b.source not in PUBLIC_BOOK_SOURCES:fail=['native_weather_book_identity_mismatch']
        elif not 0<=(now-b.available_at).total_seconds()<=15:fail=['weather_book_receipt_stale_or_future']
        else:fail=list(assess_book(b,now,max_spread=.05,expected_token=m.token_id).reasons)
        reasons[m.token_id]=fail
    for tokens in groups.values():
        fresh=[t for t in tokens if not reasons[t]]
        if fresh:
            preferred.extend(fresh)
            for token in tokens:
                if reasons[token]:deferred.append(token);counts.update(reasons[token])
    policy=digest(Path(__file__).read_text());source_sha=digest(raw);deferred_set=set(deferred);kept=[m for m in typed.markets if m.token_id not in deferred_set]
    selected=typed
    if deferred:
        selected=SharedMarketFrame.model_validate({**raw,'id':digest(['phase34-weather-fresh-siblings',policy,raw['id'],source_sha,sorted(deferred),now.isoformat()]),
            'timestamp':now.isoformat(),'available_at':now.isoformat(),'markets':[m.model_dump(mode='json') for m in kept],
            'books':[b.model_dump(mode='json') for b in typed.books if b.token_id not in deferred_set]})
    report={'schema_version':'phase34-weather-source-selection-v1','as_of':now.isoformat(),'source_frame_id':typed.id,'source_frame_sha256':source_sha,
        'selected_frame_id':selected.id,'selected_frame_sha256':digest(selected.model_dump(mode='json')),'policy_sha256':policy,'preferred_tokens':preferred,'deferred_tokens':deferred,
        'rejection_counts':dict(counts),'supported_station_days':len(groups),'scope':'source scheduling only; original model, evidence, spread, freshness, risk and forecast dedup gates unchanged',
        'research_only':True,'trading_authority':False,'certification_authority':False}
    return selected,report


def select_weather_aware_supplemental_markets(markets, *, base_tokens, adapters, as_of, maximum=32, forecast_tokens=()):
    """Preserve domain/parent slot counts while acquiring informative weather bins.

    The established selector sorts by market ID. Weather market IDs enumerate
    temperature bins, so that order favors extreme bins rather than usable
    two-sided research quotes. Replace only weather slots within the same exact
    mapped parent/station-day; retained forecast tokens keep priority. Gamma
    probability distance from0.5 schedules book acquisition, never predicts an
    event, establishes liquidity, or qualifies a forecast. Native gates remain.
    """
    from neraium_poly.contracts import MarketSnapshot
    from neraium_poly.research.phase29.alignment import select_supplemental_markets
    base=set(base_tokens);priority=set(forecast_tokens)
    selected,report=select_supplemental_markets(markets,base_tokens=base,adapters=adapters,
        as_of=as_of,maximum=maximum,forecast_tokens=priority)
    now=at(as_of);eligible=defaultdict(list);seen=set()
    for value in markets:
        m=value if isinstance(value,MarketSnapshot) else MarketSnapshot.model_validate(value)
        if m.token_id in base or m.token_id in seen:continue
        seen.add(m.token_id);mapped=weather.supports(m,cutoff=now)
        if not mapped['supported']:continue
        c=mapped['contract'];eligible[(m.event_id,c['station'],c['day'])].append(m)
    for values in eligible.values():values.sort(key=lambda m:(m.token_id not in priority,abs(m.probability-.5),m.market_id,m.token_id))
    # Retain forecast slots first; a later row must not consume their tokens.
    reserved={m.token_id for m in selected if m.token_id in priority};used=set();result=[];replacements=[]
    for m in selected:
        mapped=weather.supports(m,cutoff=now);chosen=m
        if mapped['supported'] and m.token_id not in priority:
            c=mapped['contract'];queue=eligible[(m.event_id,c['station'],c['day'])]
            chosen=next((candidate for candidate in queue if candidate.token_id not in used and candidate.token_id not in reserved),m)
        if chosen.token_id in used:raise ValueError('unique_weather_research_subscription_tokens_required')
        used.add(chosen.token_id);result.append(chosen)
        if chosen.token_id!=m.token_id:replacements.append({'previous_token':m.token_id,'selected_token':chosen.token_id,'event_id':m.event_id})
    return result,{**report,'weather_acquisition_policy':'retained forecasts, then same-parent source probability distance to0.5; not independent forecasting evidence',
        'weather_replacements':replacements,'weather_policy_sha256':digest(Path(__file__).read_text())}
