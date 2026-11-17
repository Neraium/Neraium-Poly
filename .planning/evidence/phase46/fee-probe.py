"""One bounded, read-only native fee acquisition for the actual held token."""
import asyncio
import json
from datetime import UTC,datetime
from pathlib import Path

from neraium_poly.data import EventStore
from neraium_poly.experimental.fees import AuditedFeeAdapter
from neraium_poly.research.phase29.costs import replay_fee

HERE=Path(__file__).resolve().parent
async def main():
 baseline=json.loads((HERE/'baseline.json').read_text());position=next(p for p in baseline['research']['positions'] if p['market_id']=='3215007' and p['cohort']=='phase45');store=EventStore(':memory:');adapter=AuditedFeeAdapter(store,lambda:True)
 try:
  async with asyncio.timeout(30):raw=await adapter.observed_fee(position['token_id'])
  proof=replay_fee(raw,store,token_id=position['token_id'],as_of=datetime.now(UTC))
  result={'at':datetime.now(UTC).isoformat(),'position':position,'observation':raw,'proof':proof,'historical_entry_repriced':False,'scope':'current public protocol evidence, not evidence of fee effective at prior entry','records':{kind:store.latest(kind,16) for kind in ('FeeObservation','PublicFeeResponse','PublicFeeReceipt')}}
  payload=json.dumps(result,indent=2);assert len(payload.encode())<4*1024**2;(HERE/'fee-probe.json').write_text(payload+'\n');print(json.dumps(proof))
 finally:await adapter.close();store.close()
asyncio.run(main())
