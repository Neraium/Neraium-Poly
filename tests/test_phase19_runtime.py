"""Controlled integration fixtures, never evidence of genuine market opportunities."""

from datetime import timedelta

from neraium_poly.ops.live import LivePaperRuntime
from test_live_operation import Clock, FakeAdapter, configuration


class Task:
    def __init__(self):self.finished=False
    def done(self):return self.finished


class Coverage:
    def __init__(self,adapter):self.adapter=adapter;self.starts=0;self.stops=0;self.updated=[];self.latest={}
    async def discover(self,**kwargs):return await self.adapter.discover_bounded(**kwargs)
    async def stop_stream(self):self.stops+=1
    def start_stream(self,markets,on_book):self.starts+=1;self.task=Task();return self.task
    def set_markets(self,markets):self.updated=list(markets)
    async def close(self):await self.adapter.close()
    def metrics(self):return {'ws_connected':True}


async def test_unchanged_discovery_preserves_native_stream_and_refreshes_metadata(tmp_path,now):
    clock=Clock(now);adapter=FakeAdapter(clock);r=LivePaperRuntime(configuration(tmp_path),adapter=adapter,clock=clock)
    r.coverage=Coverage(adapter)
    try:
        await r.discover();task=r._stream_task;clock.advance(301)
        await r.discover()
        assert r.coverage.starts==r.coverage.stops==1 and r._stream_task is task
        assert r.coverage.updated and r.coverage.updated[0].available_at==clock()
        assert r.state()["cash"]==500 and not r.broker.history()
    finally:await r.close()


async def test_dead_or_changed_subscription_is_restarted_without_authorizing_orders(tmp_path,now):
    clock=Clock(now);adapter=FakeAdapter(clock);r=LivePaperRuntime(configuration(tmp_path),adapter=adapter,clock=clock)
    r.coverage=Coverage(adapter)
    try:
        await r.discover();r._stream_task.finished=True;clock.advance(301);await r.discover()
        assert r.coverage.starts==2
        markets=adapter.markets
        adapter.markets=lambda:tuple(m.model_copy(update={'market_id':'controlled-new-market','token_id':'controlled-new-token'}) for m in markets()[:1])
        clock.now+=timedelta(seconds=301);await r.discover()
        assert r.coverage.starts==r.coverage.stops==3 and r.stream_generation==3
        assert r.state()["cash"]==500 and not r.broker.history()
    finally:await r.close()
