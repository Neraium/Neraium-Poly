"""One bounded production-controller rehearsal; originals/accounts stay readonly."""
import copy
import json
import time
from datetime import UTC,datetime
from pathlib import Path
from threading import RLock

from neraium_poly.data import EventStore
from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase42.controller import Controller
from neraium_poly.research.phase44.reference import ReferenceSampler
from neraium_poly.risk import RiskLimits

HERE=Path(__file__).resolve().parent
class Overlay:
 def __init__(self):
  self.original=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper');self.local=EventStore(HERE/'phase48-after.sqlite');self.catalog=self.original._connection(self.original.catalog_path);self._lock=RLock()
 def get(self,key):return self.local.get(key) or self.original.get(key)
 def latest(self,kind,limit=100):
  rows={r['id']:r for r in [*self.original.latest(kind,limit),*self.local.latest(kind,limit)]};return sorted(rows.values(),key=lambda r:(r['available_at'],r['id']),reverse=True)[:limit]
 def append(self,row):
  if (HERE/'phase48-after.sqlite').stat().st_size>64*1024**2:raise ValueError('local64MiB bound')
  return self.local.append(row)
store=Overlay();clock=lambda:datetime.now(UTC);risk=RiskLimits(**json.load(open('config/experimental-paper.example.json'))['risk_limits']).model_dump()
c=Controller(store,risk_limits=risk,clock=clock,can_write=lambda:True,directory=HERE/'native');before=copy.deepcopy(c.engine.state['profiles'])
sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame',clock=clock);cache=AsyncBudgetResearchFeeCache(store,None,clock=clock,can_write=lambda:True)
for row in store.original.latest('FeeObservation',64):cache.observations.setdefault(row['token_id'],{'evidence_id':row['id'],'observed_at':row['available_at']})
def fresh():
 for attempt in range(5):
  sampler.observe()
  try:return sampler.latest()
  except ValueError:
   if attempt==4:raise
   time.sleep(2)
for cycle in range(3):
 for attempt in range(5):
  sampler.observe()
  try:frame=sampler.latest();break
  except ValueError:
   if attempt==4:raise
   time.sleep(2)
 fees=cache.proofs(as_of=clock());report=c.tick(frame,fees,frame_provider=fresh);time.sleep(1)
assert c.engine.state['profiles']['aggressive']['cash']==before['aggressive']['cash']
assert c.engine.state['profiles']['aggressive']['suspended']==before['aggressive']['suspended']
assert all(c.engine.state['profiles'][n]['closed'][:len(s['closed'])]==s['closed'] for n,s in before.items())
result={'scope':'isolated production controller; authentic current reference snapshots; no account or service modifications','at':clock().isoformat(),'frames':3,'fresh_books':len(frame.books),'markets':len(frame.markets),'fee_proofs':{t:p['status'] for t,p in fees.items()},'report':report}
(HERE/'controller-after.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('frames','fresh_books','markets','at')}));print(json.dumps({'forecasts':report['forecasts'],'parent_events':report['parent_events'],'native_labels':report['verified_outcomes'],'explorer':report['phase45_explorer']['profiles'],'panel':report['probability_panel']}))
