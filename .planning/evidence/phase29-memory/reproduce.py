"""Controlled delta-engine allocation probe using an authentic captured baseline.

The repeated replacements are mechanical fixtures, not claimed exchange messages.
Run separately against baseline/fixed source; no active service writes.
"""
import asyncio,importlib.util,json,resource,subprocess,sys,time
from datetime import UTC,datetime
from pathlib import Path

import httpx
from neraium_poly.contracts import MarketSnapshot,OrderBookSnapshot
from neraium_poly.data.operational import OperationalPolymarketAdapter

async def main():
    mode=sys.argv[1];root=Path('/home/ubuntu/Neraium-Poly')
    frame=json.loads((root/'data/phase29/live-before.json').read_text())['frame']
    markets={m['token_id']:m for m in frame['markets']}
    book=max((b for b in frame['books'] if b['bids'] and b['asks']),key=lambda b:len(b['bids'])+len(b['asks']))
    source=(subprocess.check_output(['git','show','dc2742c:backend/neraium_poly/data/connectivity.py'],text=True)
            if mode=='baseline' else Path('backend/neraium_poly/data/connectivity.py').read_text())
    # Relative imports need package context. No source or runtime module changes.
    import types
    module=types.ModuleType('neraium_poly.data.memory_probe');module.__package__='neraium_poly.data'
    exec(compile(source,'controlled_connectivity_probe','exec'),module.__dict__)
    now=datetime.fromisoformat(book['available_at'].replace('Z','+00:00'))
    market=MarketSnapshot.model_validate(markets[book['token_id']])
    native=OrderBookSnapshot.model_validate(book)
    client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(503)))
    adapter=OperationalPolymarketAdapter(client=client,clock=lambda:now,min_interval=0)
    feed=module.CoverageFeed(adapter,rate=20);feed.set_markets([market]);feed.latest[native.token_id]=native
    constructed=0;original=module.PriceLevel
    def count(**values):
        nonlocal constructed
        constructed+=1;return original(**values)
    module.PriceLevel=count;start=time.monotonic()
    for i in range(300):
        event={'event_type':'price_change','timestamp':str(int(native.timestamp.timestamp()*1000)),
            'price_changes':[{'asset_id':native.token_id,'side':'BUY','price':str(native.bids[0].price),'size':str(native.bids[0].size+i+1)}]}
        [updated]=await feed.handle(event)
        assert len(updated.bids)==len(native.bids) and len(updated.asks)==len(native.asks)
    result={'mode':mode,'at':datetime.now(UTC).isoformat(),'scope':'controlled repeated replacement fixture on authentic captured native book; not prospective exchange traffic, performance or sole OOM attribution',
        'book_id':native.id,'market_id':native.market_id,'token_id':native.token_id,'native_timestamp':native.timestamp.isoformat(),
        'baseline_levels':len(native.bids)+len(native.asks),'updates':300,'new_price_level_instances':constructed,
        'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    await feed.close();await client.aclose();print(json.dumps(result))
asyncio.run(main())
