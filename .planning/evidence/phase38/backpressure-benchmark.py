"""Identical controlled bursts and slow consumer; not market performance."""
import asyncio,json,subprocess,sys,time
from datetime import UTC,datetime
sys.path.insert(0,'tests')
from test_connectivity import Socket,full
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data.connectivity import CoverageFeed,StreamGap
from neraium_poly.data.operational import OperationalPolymarketAdapter
ns={'__name__':'neraium_poly.data.phase38_baseline','__package__':'neraium_poly.data'}
exec(subprocess.check_output(['git','show','7399fb4:backend/neraium_poly/data/connectivity.py'],text=True),ns)

async def run(cls):
    now=datetime.now(UTC)
    market=MarketSnapshot(timestamp=now,available_at=now,source='CONTROLLED',market_id='m1',token_id='t1',event_id='e1',question='CONTROLLED?',probability=.4)
    socket=Socket([json.dumps([full(now)]*20) for _ in range(4)])
    f=cls(OperationalPolymarketAdapter(clock=lambda:now),queue_size=4,max_reconnects=0,connector=lambda *a,**k:socket)
    delivered=[]
    async def slow(b):
        await asyncio.sleep(.001);delivered.append(b.id)
    start=time.monotonic();task=f.start_stream([market],slow)
    try:
        async with asyncio.timeout(5):
            while len(delivered)<80 and not task.done():await asyncio.sleep(.005)
        failure=None
        if task.done():
            try:task.result()
            except (StreamGap,ns['StreamGap']) as e:failure=str(e)
        m=f.metrics()
        return {'offered':80,'delivered':len(delivered),'seconds':time.monotonic()-start,'failure':failure,
                'metrics':{k:m.get(k) for k in ['reconnects','queue_overflows','queue_backpressure_waits','queue_backpressure_seconds','queue_peak_depth','queue_peak_bytes','consumer_max_seconds']}}
    finally:await f.close()
async def main():
    print(json.dumps({'kind':'CONTROLLED fixture, no financial result','same_queue_size':4,'same_callback_delay_seconds':.001,'before':await run(ns['CoverageFeed']),'after':await run(CoverageFeed)}))
asyncio.run(main())
