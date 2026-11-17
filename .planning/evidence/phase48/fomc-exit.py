"""Fresh public fee/book observation; never places or records an exit fill."""
import asyncio
import json
from datetime import UTC,datetime
from pathlib import Path

from neraium_poly.data import EventStore,assess_book
from neraium_poly.experimental.fees import AuditedFeeAdapter
from neraium_poly.research.phase29.costs import replay_fee

HERE=Path(__file__).resolve().parent
async def main():
 position=next(p for p in json.loads((HERE/'before-observation/result.json').read_text())['final']['research']['positions'] if p['cohort']=='phase45' and p['market_id']=='3215007');store=EventStore(':memory:');adapter=AuditedFeeAdapter(store,lambda:True)
 try:
  async with asyncio.timeout(30):
   fee=await adapter.observed_fee(position['token_id']);book=await adapter.book(position['market_id'],position['token_id'])
  now=datetime.now(UTC);proof=replay_fee(fee,store,token_id=position['token_id'],as_of=now);quality=assess_book(book,now,max_age_seconds=15,max_spread=.25,expected_token=position['token_id']);remaining=position['quantity'];gross=fees=slip=0.
  if quality.healthy and proof['status']=='verified_current_protocol_curve':
   for l in book.bids[:8]:
    q=min(remaining,l.size*.1);gross+=q*l.price;fees+=q*proof['rate']*l.price*(1-l.price);slip+=q*.0015;remaining-=q
  result={'at':now.isoformat(),'position':position,'fee_proof':proof,'book':book.model_dump(mode='json'),'book_quality':quality.model_dump(mode='json') if hasattr(quality,'model_dump') else str(quality),'full_quantity_observable':remaining<=1e-8,
    'indicative_gross_exit_value':gross if remaining<=1e-8 else None,'formula_exit_fee':fees if remaining<=1e-8 else None,'modeled_exit_slippage':slip if remaining<=1e-8 else None,'indicative_net_pnl':gross-fees-slip-position['capital'] if remaining<=1e-8 else None,
    'actual_fill':False,'exit_performed':False,'entry_repriced':False,'assumptions':'10% depth participation, first8bid levels, modeled0.0015/share exit slippage; full all-in cost evidence unavailable',
    'records':{k:store.latest(k,16) for k in ('FeeObservation','PublicFeeResponse','PublicFeeReceipt')}}
  (HERE/('fomc-exit-'+now.strftime('%Y%m%dT%H%M%S')+'.json')).write_text(json.dumps(result,indent=2)+'\n');print({k:result[k] for k in ('at','full_quantity_observable','indicative_net_pnl','actual_fill','exit_performed')})
 finally:await adapter.close();store.close()
asyncio.run(main())
