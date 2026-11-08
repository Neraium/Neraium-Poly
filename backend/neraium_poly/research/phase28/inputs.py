"""Compose current existing observations; never redate native quotes."""
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at


def current_frame(primary, *, extra_markets=(), extra_books=(), as_of):
    now=at(as_of)
    frame=SharedMarketFrame.model_validate(primary.model_dump() if hasattr(primary,'model_dump') else primary)
    if not 0 <= (now-frame.available_at).total_seconds() <= 15:
        raise ValueError('fresh_primary_research_frame_required')
    markets={m.token_id:m for m in frame.markets};books={b.token_id:b for b in frame.books}
    for m in extra_markets:
        m=MarketSnapshot.model_validate(m.model_dump() if hasattr(m,'model_dump') else m)
        if max(m.timestamp,m.available_at)>now:raise ValueError('future_supplemental_metadata')
        if m.token_id in markets:
            old=markets[m.token_id]
            if (old.market_id,old.event_id,old.outcome,old.question,old.resolution_rules,old.resolution_source,old.end_time,old.tick_size,old.min_order_size)!=(m.market_id,m.event_id,m.outcome,m.question,m.resolution_rules,m.resolution_source,m.end_time,m.tick_size,m.min_order_size):
                raise ValueError('conflicting_supplemental_market_identity')
        else:markets[m.token_id]=m
    for b in extra_books:
        b=OrderBookSnapshot.model_validate(b.model_dump() if hasattr(b,'model_dump') else b)
        if b.token_id not in markets or b.market_id!=markets[b.token_id].market_id:
            raise ValueError('supplemental_native_book_identity_mismatch')
        if max(b.timestamp,b.available_at)>now:raise ValueError('future_supplemental_book')
        if b.token_id not in books or b.timestamp>books[b.token_id].timestamp:books[b.token_id]=b
    connectivity={**frame.connectivity,'research_primary_frame_id':frame.id,'research_primary_available_at':frame.available_at.isoformat(),
                  'research_composition':'native market/book clocks unchanged; composition clock is not quote freshness'}
    identity=digest(['current-research-frame',frame.id,now.isoformat(),sorted((t,b.id) for t,b in books.items()),sorted(markets)])
    return frame.model_copy(update={'id':identity,'timestamp':now,'available_at':now,'source':'neraium-poly/current-research-frame/v28',
        'markets':tuple(markets.values()),'books':tuple(books.values()),'connectivity':connectivity})
