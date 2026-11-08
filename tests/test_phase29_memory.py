"""Controlled engineering fixtures; no market performance or OOM-elimination claim."""
import httpx
import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.data.connectivity import CoverageFeed
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.data.polymarket import stable_id
from neraium_poly.data.stream import MARKET_WS


@pytest.fixture
async def memory_feed(now, market):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    adapter = OperationalPolymarketAdapter(client=client, clock=lambda: now, min_interval=0)
    feed = CoverageFeed(adapter, rate=20)
    feed.set_markets([market])
    book = OrderBookSnapshot(id='memory-base', timestamp=now, available_at=now, source=MARKET_WS,
        market_id=market.market_id,token_id=market.token_id,
        bids=tuple(PriceLevel(price=.49-i/10000,size=100+i) for i in range(400)),
        asks=tuple(PriceLevel(price=.51+i/10000,size=200+i) for i in range(400)))
    feed.latest[market.token_id]=book
    yield feed,book
    await feed.close()
    await client.aclose()


def event(now, token, updates):
    return {'event_type':'price_change','timestamp':str(int(now.timestamp()*1000)),
        'price_changes':[{'asset_id':token, **value} for value in updates]}


async def test_single_level_replacement_reuses_frozen_unchanged_levels(memory_feed,now):
    feed,old=memory_feed
    [new]=await feed.handle(event(now,old.token_id,[{'side':'BUY','price':'.49','size':'33'}]))
    assert new.bids[0].size==33 and old.bids[0].size==100
    assert new.bids[0] is not old.bids[0]
    assert all(a is b for a,b in zip(new.bids[1:],old.bids[1:]))
    assert all(a is b for a,b in zip(new.asks,old.asks))
    assert len(new.bids)+len(new.asks)==800
    with pytest.raises(ValueError):new.asks[0].size=5


async def test_unchanged_replacements_allocate_no_new_levels(memory_feed,now,monkeypatch):
    from neraium_poly.data import connectivity
    feed,old=memory_feed;created=[]
    original=connectivity.PriceLevel
    def count(**values):
        created.append(values);return original(**values)
    monkeypatch.setattr(connectivity,'PriceLevel',count)
    for _ in range(50):
        [new]=await feed.handle(event(now,old.token_id,[{'side':'BUY','price':'.4900','size':'100.000'}]))
        assert all(a is b for a,b in zip(new.bids,old.bids))
    assert created==[]


async def test_changed_level_allocation_is_proportional_to_updated_levels(memory_feed,now,monkeypatch):
    from neraium_poly.data import connectivity
    feed,old=memory_feed;created=[];original=connectivity.PriceLevel
    def count(**values):created.append(values);return original(**values)
    monkeypatch.setattr(connectivity,'PriceLevel',count)
    for size in range(1,51):
        [new]=await feed.handle(event(now,old.token_id,[{'side':'BUY','price':'.49','size':str(size)}]))
        assert new.bids[0].size==size
    assert len(created)==50  # Previous whole-book reconstruction allocated40,000.


async def test_deletion_insertion_and_exact_identity_preserved(memory_feed,now):
    feed,old=memory_feed
    [new]=await feed.handle(event(now,old.token_id,[{'side':'BUY','price':'.49','size':'0'},
        {'side':'BUY','price':'.4901','size':'7'}, {'side':'SELL','price':'.51','size':'9'}]))
    values={'timestamp':now,'available_at':now,'source':MARKET_WS,'market_id':old.market_id,
        'token_id':old.token_id,'bids':(PriceLevel(price=.4901,size=7),*old.bids[1:]),
        'asks':(PriceLevel(price=.51,size=9),*old.asks[1:]),'sequence':0,'complete':True}
    expected=OrderBookSnapshot(id=stable_id('ws-book',values),**values)
    assert expected==new
    assert len(old.bids)==400 and old.bids[0].price==.49
    assert new.bids[1] is old.bids[1] and new.asks[1] is old.asks[1]
