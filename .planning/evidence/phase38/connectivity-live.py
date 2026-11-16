"""60-second read-only public feed probe; no broker/account/archive writer."""
import asyncio,json,resource,statistics,time
from datetime import UTC,datetime
from neraium_poly.data.connectivity import CoverageFeed
from neraium_poly.data.quality import assess_book
from neraium_poly.experimental.feed import SharedFeedClient

async def main():
    feed=CoverageFeed(max_tokens=32,queue_size=64)
    batch=await feed.discover(max_markets=8,page_size=8,max_pages=1)
    markets=list(batch.markets)
    counts={'callbacks':0,'qualified_callbacks':0}; lags=[];samples=[]
    def observed(b):
        counts['callbacks']+=1
        counts['qualified_callbacks']+=int(assess_book(b,datetime.now(UTC)).healthy)
    async def lag():
        while True:
            target=time.monotonic()+.02
            await asyncio.sleep(.02)
            lags.append(max(0,time.monotonic()-target))
    start=time.monotonic();started=datetime.now(UTC).isoformat()
    loop_task=asyncio.create_task(lag()); stream=feed.start_stream(markets,observed)
    try:
        async with asyncio.timeout(70):
            for _ in range(12):
                await asyncio.sleep(5)
                samples.append({'at':datetime.now(UTC).isoformat(),**feed.metrics()})
                if stream.done():
                    stream.result()
                    break
    finally:
        before_close=feed.metrics()
        await feed.close();loop_task.cancel()
        await asyncio.gather(loop_task,return_exceptions=True)
    sorted_lags=sorted(lags)
    print(json.dumps({'started_at':started,'seconds':time.monotonic()-start,'tokens':len(markets),
      'read_only':True,'source':'public Polymarket WebSocket; genuine observations, no execution',
      'counts':counts,'metrics':before_close,'shutdown':feed.metrics(), 'samples':samples,
      'event_loop_lag_p99_seconds': sorted_lags[int(.99*(len(sorted_lags)-1))] if sorted_lags else None,
      'max_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}))
asyncio.run(main())
