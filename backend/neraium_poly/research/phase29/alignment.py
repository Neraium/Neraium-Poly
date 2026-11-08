"""Native forecast/book joins and bounded subscriptions, never trade authority."""
import hashlib
from collections import Counter, defaultdict

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase25.dependencies import at


def select_supplemental_markets(markets, *, base_tokens, adapters, as_of, maximum=32, forecast_tokens=()):
    """Watch all supported domains, with deterministic parent-first capacity.

    Current Gamma metadata only. Existing native base subscriptions are reused;
    forecasts only prioritize reviewed current candidates, never invent metadata.
    """
    if type(maximum) is not int or not 1<=maximum<=32:raise ValueError('supplemental32_token_budget_required')
    if len(markets)>4096:raise ValueError('bounded_supplemental_market_universe_required')
    now=at(as_of);base=set(base_tokens);priority=set(forecast_tokens);eligible=[];seen={};rejected=Counter()
    for value in markets:
        m=MarketSnapshot.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
        if m.token_id in base:continue
        identity=(m.market_id,m.event_id,m.question,m.outcome,m.resolution_rules,m.resolution_source,m.end_time,m.tick_size,m.min_order_size)
        if m.token_id in seen:
            if seen[m.token_id]!=identity:raise ValueError('ambiguous_supplemental_token_identity')
            continue
        seen[m.token_id]=identity
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
                or not m.end_time or m.end_time<=now or not m.timestamp<=m.available_at<=now):
            rejected['noncausal_or_inactive_metadata']+=1;continue
        supported=sorted(name for name,adapter in adapters.items()
            if adapter.supports(m,cutoff=now).get('supported'))
        if not supported:rejected['no_supported_adapter']+=1;continue
        eligible.append((0 if m.token_id in priority else 1,m.end_time,m.event_id,m.market_id,m.token_id,supported[0],m))
    eligible.sort(key=lambda r:r[:5]);bydomain=defaultdict(list)
    for item in eligible:bydomain[item[5]].append(item)
    selected=[];events=set()
    # First pass covers distinct parents across domains; second adds outcome sides.
    for unique in (True,False):
        queues={name:list(values) for name,values in bydomain.items()}
        while len(selected)<maximum:
            progress=False
            for name in sorted(queues):
                values=queues[name]
                while values:
                    row=values.pop(0);m=row[-1]
                    if any(x.token_id==m.token_id for x in selected):continue
                    if unique and m.event_id in events:continue
                    selected.append(m);events.add(m.event_id);progress=True;break
                if len(selected)==maximum:break
            if not progress:break
    return selected,{'eligible_tokens':len(eligible),'selected_tokens':len(selected),'deferred_tokens':len(eligible)-len(selected),
        'selected_parent_events':len(events),'selected_domains':dict(Counter(next(x[5] for x in eligible if x[-1].token_id==m.token_id) for m in selected)),
        'rejections':dict(rejected),'maximum_tokens':maximum,'trading_authority':False}


def classify_alignment(forecasts, frame, *, as_of, subscribed_tokens=(), supplemental_status=None):
    """Explain data joins separately from forecast evidence/admission blockers.

    Accepts original forecasts or immutable finding rows. A source-matched fresh
    book is reported even when the original forecast is old; that never redates
    the forecast or establishes current executable EV.
    """
    if len(forecasts)>128:raise ValueError('bounded_forecast_alignment_required')
    now=at(as_of);raw=frame.model_dump() if hasattr(frame,'model_dump') else frame
    f=SharedMarketFrame.model_validate(raw);markets={m.token_id:m for m in f.markets};books={b.token_id:b for b in f.books}
    if len(markets)!=len(f.markets) or len(books)!=len(f.books):raise ValueError('unique_native_alignment_tokens_required')
    subscribed=set(subscribed_tokens);details=(supplemental_status or {}).get('token_diagnostics',{});rows=[];counts=Counter();categories=Counter()
    for forecast in forecasts:
        token=forecast.get('token_id');m=markets.get(token);b=books.get(token);reasons=[]
        created=forecast.get('forecast_timestamp',forecast.get('timestamp'));event_end=forecast.get('event_end_time')
        ended='forecast_event_decision_horizon_ended' in forecast.get('reasons',()) or bool(event_end and at(event_end)<=now)
        fresh_forecast=bool(created and 0<=(now-at(created)).total_seconds()<=300)
        if not fresh_forecast:reasons.append('forecast_not_current_300_seconds')
        if ended:reasons.append('forecast_event_horizon_ended')
        expected_rules=forecast.get('rules_sha256',forecast.get('resolution_rules_sha256'))
        original=forecast.get('market',{});reference=forecast.get('resolution_source',original.get('resolution_source'))
        exact=bool(m and m.market_id==forecast.get('market_id') and m.event_id==forecast.get('event_id')
            and m.token_id==token and m.exchange=='polymarket' and m.timestamp<=m.available_at<=now
            and (not expected_rules or hashlib.sha256(m.resolution_rules.encode()).hexdigest()==expected_rules)
            and (reference is None or m.resolution_source==reference)
            and all(original.get(k) is None or original[k]==getattr(m,k) for k in ('outcome','question'))
            and (original.get('end_time') is None or at(original['end_time'])==m.end_time))
        if m and not exact:category='IDENTITY_DEFECT';cause='current_market_resolution_identity_mismatch'
        elif m is None:category='EVENT_LIFECYCLE' if ended else 'DISCOVERY_COVERAGE';cause='ended_event_not_in_active_universe' if ended else 'current_exact_metadata_not_discovered'
        elif b is None:
            diagnostics=details.get(token,{})
            if ended:category='EVENT_LIFECYCLE';cause='ended_event_book_not_required_for_new_entry'
            elif 'transport_gap_withheld' in diagnostics.get('reasons',()):category='TRANSPORT_INTEGRITY';cause='native_book_withheld_after_detected_gap'
            elif token not in subscribed:category='SUBSCRIPTION_COVERAGE';cause='current_token_not_subscribed'
            else:category='MARKET_DATA_UNAVAILABLE';cause='no_current_native_book_observation'
        elif b.market_id!=forecast.get('market_id') or b.token_id!=token or b.exchange!='polymarket' or b.source not in PUBLIC_BOOK_SOURCES:
            category='IDENTITY_DEFECT';cause='native_book_identity_or_source_mismatch'
        else:
            quote=assess_book(b,now,max_age_seconds=15,max_spread=1.,expected_token=token)
            bad=list(quote.reasons)
            if not 0<=(now-b.available_at).total_seconds()<=15:bad.append('book_receipt_outside_15_seconds')
            if b.timestamp>b.available_at:bad.append('native_book_clock_order_invalid')
            reasons.extend(bad)
            if bad:category='MARKET_DATA_QUALITY';cause='native_book_not_current_or_executable'
            elif m.status!='active' or m.end_time is not None and m.end_time<=now:category='EVENT_LIFECYCLE';cause='native_market_not_open_for_entry'
            else:category='MATCHED_EXECUTABLE_BOOK';cause='exact_current_native_two_sided_book'
        executable=category=='MATCHED_EXECUTABLE_BOOK';counts['findings_considered']+=1;counts['exact_metadata_matches']+=exact
        counts['native_book_observations']+=b is not None;counts['authentically_matched_executable_books']+=executable
        counts['current_forecasts_with_executable_books']+=executable and fresh_forecast and not ended
        categories[category]+=1;reasons.append(cause)
        rows.append({'forecast_id':forecast.get('forecast_id',forecast.get('id')),'market_id':forecast.get('market_id'),
            'event_id':forecast.get('event_id'),'token_id':token,'category':category,'cause':cause,'reasons':sorted(set(reasons)),
            'metadata_identity_verified':exact,'forecast_current':fresh_forecast,'event_horizon_ended':ended,
            'native_book_present':b is not None,'current_executable_book_matched':executable,
            'book_id':b.id if b else None,'book_source_timestamp':b.timestamp.isoformat() if b else None,
            'book_available_at':b.available_at.isoformat() if b else None,'trading_authority':False})
    return {'schema_version':'phase29-native-alignment-v1','as_of':now.isoformat(),'counts':dict(counts),
        'categories':dict(categories),'findings':rows,'counter_scope':'one evaluation; repeated models/events are not independent outcomes',
        'research_only':True,'trading_authority':False,'certification_authority':False}
