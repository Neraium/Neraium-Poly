"""Bounded live rehearsal of the exact service controller, never account execution."""
import argparse
import asyncio
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from neraium_poly.data import EventStore
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.fees import AuditedFeeAdapter
from neraium_poly.research.phase29.costs import ResearchFeeCache
from neraium_poly.research.phase40.campaign import FEED
from neraium_poly.research.phase40.campaign import run as acquire
from neraium_poly.research.phase42.controller import Controller


async def run(output,seconds=180):
    if not 60<=seconds<=900:raise ValueError('bounded60–900second rehearsal required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    clock=lambda:datetime.now(UTC)
    def can_write():return shutil.disk_usage(output).free>100*1024**3+16*1024**2 and sum(p.stat().st_size for p in output.rglob('*') if p.is_file())<112*1024**2
    source=output/'source';await acquire(source,seconds=120)
    store=EventStore(source/'campaign.sqlite');risk=json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits']
    controller=Controller(store,risk_limits=risk,clock=clock,can_write=can_write,directory=output/'native')
    fees=AuditedFeeAdapter(store,can_write,clock=clock);cache=ResearchFeeCache(store,fees,clock=clock,can_write=can_write)
    report=None;errors=[];started=time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            while time.monotonic()-started<seconds:
                try:
                    response=await client.get(FEED);response.raise_for_status();frame=SharedMarketFrame.model_validate(response.json())
                    await cache.refresh(frame,forecast_tokens=[m.token_id for m in frame.markets])
                    report=await asyncio.to_thread(controller.tick,frame,cache.proofs(as_of=clock()))
                except (ValueError,OSError,httpx.HTTPError) as error:errors.append(f'{type(error).__name__}:{str(error)[:160]}')
                if len(errors)>=10:break
                await asyncio.sleep(5)
        result={'report':report,'errors':errors,'elapsed_seconds':time.monotonic()-started,'scope':'bounded authentic observations; modeled entries/exits NOT actual account trades'}
        (output/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result
    finally:await fees.close();store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--seconds',type=int,default=180);args=parser.parse_args()
    print(json.dumps(asyncio.run(run(args.output,args.seconds))))


if __name__=='__main__':main()
