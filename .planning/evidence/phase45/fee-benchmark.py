"""Frozen warm-cache engineering control; no market/profitability claim."""
import asyncio
import json
from datetime import UTC,datetime,timedelta
from pathlib import Path
from types import SimpleNamespace

from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
from neraium_poly.research.phase29.costs import ResearchFeeCache
from test_experimental_account import book,market

now=datetime(2026,11,8,tzinfo=UTC);m=market(now);b=book(now)
markets=tuple(m.model_copy(update={'token_id':str(i),'market_id':'CONTROLLED-'+str(i)}) for i in range(4))
books=tuple(b.model_copy(update={'token_id':v.token_id,'market_id':v.market_id}) for v in markets);frame=SimpleNamespace(markets=markets,books=books)
async def run(cls):
 calls=[]
 async def observe(token):calls.append(token)
 cache=cls(None,SimpleNamespace(observed_fee=observe),clock=lambda:now,can_write=lambda:True)
 for token in ('0','1'):
  cache.observations[token]={'observed_at':(now-timedelta(seconds=90)).isoformat()};cache.attempts[token]=now-timedelta(seconds=90)
 for token in ('2','3'):cache.attempts[token]=now-timedelta(seconds=60)
 await cache.refresh(frame,forecast_tokens=('0','1','2','3'))
 return calls
before=asyncio.run(run(ResearchFeeCache));after=asyncio.run(run(AsyncBudgetResearchFeeCache));assert before==[] and after==['2','3']
r={'scope':'controlled deterministic engineering case, not authentic economic performance','warm_cache_seconds':90,'retry_age_seconds':60,'batch_cap':2,'old_due_attempts':before,'new_due_attempts':after,'native_requests_per_token_max':2,'cache_cap':32}
Path(__file__).with_suffix('.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
