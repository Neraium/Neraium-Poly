"""Controlled native transport fixtures, never authentic market performance."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.data.connectivity import CoverageFeed
from neraium_poly.data.stream import MARKET_WS
from neraium_poly.research.phase26.books import SupplementalBooks

NOW=datetime(2026,11,8,tzinfo=UTC)


def market(token='token'):
    return MarketSnapshot(id=token,timestamp=NOW,available_at=NOW,source='https://gamma-api.polymarket.com',
        market_id='market-'+token,event_id='parent',token_id=token,outcome='Yes',question='Controlled target?',
        probability=.5,status='active',end_time=NOW+timedelta(days=1),resolution_rules='Controlled exact rules',resolution_source='https://official.example')


def book(m,**updates):
    b=OrderBookSnapshot(id='book-'+m.token_id,timestamp=NOW,available_at=NOW,source=MARKET_WS,market_id=m.market_id,
        token_id=m.token_id,bids=(PriceLevel(price=.48,size=50),),asks=(PriceLevel(price=.49,size=40),))
    return b.model_copy(update=updates)


class FakeFeed:
    def __init__(self):self.latest={};self.starts=0;self.closed=False;self.stops=0;self.task=None
    def set_markets(self,markets):self.markets=markets
    def start_stream(self,markets,callback):
        self.starts+=1;self.markets=markets;self.callback=callback
        self.task=asyncio.create_task(asyncio.Event().wait());return self.task
    async def stop_stream(self):
        self.stops+=1;self.latest.clear()
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        self.task=None
    async def close(self):await self.stop_stream();self.closed=True
    def metrics(self):return {'ws_connected':self.task is not None}


async def test_bounded_subscription_reuse_and_native_cache_invalidation():
    f=FakeFeed();m=market();w=SupplementalBooks(clock=lambda:NOW,feed=f)
    try:
        assert await w.update([m]);assert not await w.update([m.model_copy(update={'probability':.6})]);assert f.starts==1
        b=book(m);f.latest[m.token_id]=b
        assert w.snapshot()==(b,)
        f.latest.clear();assert w.snapshot()==() and w.status()['book_rejections']=={'missing_book':1}
        await w.update([market('second')]);assert f.starts==2 and w.snapshot()==()
    finally:await w.close()
    assert f.closed and w.snapshot()==()


@pytest.mark.parametrize('field,value',[('question','changed'),('event_id','different'),('end_time',NOW+timedelta(hours=2)),('tick_size',.001),('min_order_size',3)])
async def test_changed_contract_identity_quarantines_and_clears(field,value):
    f=FakeFeed();m=market();w=SupplementalBooks(clock=lambda:NOW,feed=f)
    try:
        await w.update([m]);f.latest[m.token_id]=book(m)
        with pytest.raises(ValueError,match='identity_conflict'):await w.update([m.model_copy(update={field:value})])
        assert w.snapshot()==() and w.status()['quarantined_tokens']==1
        with pytest.raises(ValueError):await w.update([m.model_copy(update={field:value})])
    finally:await w.close()


async def test_duplicate_identity_future_metadata_and_subscription_cap_reject():
    f=FakeFeed();m=market();w=SupplementalBooks(clock=lambda:NOW,feed=f)
    try:
        await w.update([m]);f.latest[m.token_id]=book(m)
        with pytest.raises(ValueError,match='ambiguous'):await w.update([m,m.model_copy(update={'question':'conflict'})])
        assert not w.snapshot()
        with pytest.raises(ValueError,match='causal'):await w.update([m.model_copy(update={'available_at':NOW+timedelta(seconds=1)})])
        with pytest.raises(ValueError,match='32_token'):await w.update([market(str(i)) for i in range(33)])
    finally:await w.close()


@pytest.mark.parametrize('change,reason',[
    ({'timestamp':NOW-timedelta(seconds=16)},'stale_book'),
    ({'timestamp':NOW+timedelta(seconds=1)},'future_data'),
    ({'complete':False},'incomplete_book'),
    ({'asks':(PriceLevel(price=.7,size=1),)},'large_spread'),
    ({'market_id':'wrong'},'book_market_identity_mismatch'),
    ({'source':'fixture://synthetic'},'nonpublic_book_source')])
async def test_quality_never_restamps_or_infers_executable_depth(change,reason):
    f=FakeFeed();m=market();w=SupplementalBooks(clock=lambda:NOW,feed=f);received=[];w.on_book=received.append
    try:
        await w.update([m]);b=book(m,**change);f.latest[m.token_id]=b;before=b.model_dump(mode='json')
        await w._accept(b);assert not received and not w.snapshot()
        assert reason in w.status()['book_rejections'] and b.model_dump(mode='json')==before
    finally:await w.close()


async def test_waiters_shutdown_and_current_source_time_are_preserved():
    f=FakeFeed();m=market();clock=[NOW];seen=[];w=SupplementalBooks(clock=lambda:clock[0],feed=f,on_book=seen.append)
    await w.update([m]);task=asyncio.create_task(w.wait_fresh(timeout=2));await asyncio.sleep(0)
    b=book(m);f.latest[m.token_id]=b;await w._accept(b)
    assert await task==(b,) and seen==[b]
    clock[0]+=timedelta(seconds=16);assert not w.snapshot()
    waiter=asyncio.create_task(w.wait_fresh(timeout=2));await asyncio.sleep(0);await w.close();assert await waiter==()
    with pytest.raises(ValueError,match='closed'):await w.update([m])


async def test_reuses_existing_delta_reconstruction_and_gap_withholding():
    import httpx
    from neraium_poly.data.operational import OperationalPolymarketAdapter
    async def unavailable(request):return httpx.Response(503,request=request)
    client=httpx.AsyncClient(transport=httpx.MockTransport(unavailable));adapter=OperationalPolymarketAdapter(client=client,clock=lambda:NOW,retries=1)
    f=CoverageFeed(adapter,max_tokens=32,concurrency=2,rate=2,queue_size=64);m=market();w=SupplementalBooks(clock=lambda:NOW,feed=f)
    f.set_markets([m]);w._markets={m.token_id:m}
    try:
        raw={'event_type':'book','asset_id':m.token_id,'timestamp':str(int(NOW.timestamp()*1000)),
             'bids':[{'price':'.48','size':'50'}],'asks':[{'price':'.49','size':'40'}]}
        books=await f.handle(raw);assert len(books)==1 and w.snapshot()[0].bids[0].size==50
        # An unknown/malformed level invalidates instead of fabricating depth.
        await f.handle({'event_type':'price_change','timestamp':raw['timestamp'],'price_changes':[{'asset_id':m.token_id,'side':'BUY','price':'.5','size':'-1'}]})
        assert w.snapshot()==()
    finally:await w.close();await client.aclose()


async def test_concurrent_shutdown_cannot_start_a_new_socket_after_close():
    f=FakeFeed();w=SupplementalBooks(clock=lambda:NOW,feed=f)
    await w._lock.acquire()
    closing=asyncio.create_task(w.close());updating=asyncio.create_task(w.update([market()]));await asyncio.sleep(0)
    w._lock.release();await closing
    with pytest.raises(ValueError,match='closed'):await updating
    assert f.closed and f.starts==0
