"""One public subscription, bounded raw capture, no order client."""
import asyncio
import gzip
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.data.stream import MARKET_WS
from websockets.asyncio.client import connect


async def run():
    root=Path(__file__).resolve().parent
    market=json.loads((root/'market-identity.json').read_bytes())
    tokens=[market['secondary_token_id'],market['primary_token_id']]
    async with connect(MARKET_WS,open_timeout=12,close_timeout=3,ping_interval=None,max_size=4*1024**2) as ws:
        await ws.send(json.dumps({'assets_ids':tokens,'type':'market'}))
        start=time.monotonic()
        end=start+300
        ping=start
        with gzip.open(sys.argv[1],'xt') as out:
            size=0
            while time.monotonic()<end:
                if time.monotonic()>=ping:
                    await ws.send('PING')
                    ping=time.monotonic()+10
                try:
                    raw=await asyncio.wait_for(ws.recv(),min(2,max(.01,end-time.monotonic())))
                except TimeoutError:
                    continue
                arrived=datetime.now(UTC).isoformat()
                size+=len(raw)
                if size>32*1024**2:
                    raise ValueError('capture byte limit')
                out.write(json.dumps({'received_at':arrived,'raw':raw},separators=(',',':'))+'\n')
asyncio.run(run())
