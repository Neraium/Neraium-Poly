"""Single local production-controller rehearsal on authentic reference observations.

Original archives stay readonly. Separate local writes/proof cache cannot touch
accounts, financial brokers, emergency stops or running service configuration.
"""
import copy,json,time,shutil
from datetime import UTC,datetime
from pathlib import Path
from threading import RLock

from neraium_poly.data import EventStore
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase29.costs import replay_fee
from neraium_poly.research.phase42.controller import Controller
from neraium_poly.research.phase44.reference import ReferenceSampler
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase44.outcomes import NativePayout44,collect
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.risk import RiskLimits
import asyncio

HERE=Path(__file__).resolve().parent
class Overlay:
 def __init__(self):
  self.original=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper');self.local=EventStore(HERE/'rehearsal-v2.sqlite');self.catalog=self.original._connection(self.original.catalog_path);self._lock=RLock()
 def get(self,key):return self.local.get(key) or self.original.get(key)
 def latest(self,kind,limit=100):
  rows={r['id']:r for r in [*self.original.latest(kind,limit),*self.local.latest(kind,limit)]};return sorted(rows.values(),key=lambda r:(r['available_at'],r['id']),reverse=True)[:limit]
 def append(self,row):
  if (HERE/'rehearsal-v2.sqlite').stat().st_size>64*1024**2:raise ValueError('local rehearsal64MiB bound')
  return self.local.append(row)

store=Overlay();clock=lambda:datetime.now(UTC);risk=RiskLimits(**json.load(open('config/experimental-paper.example.json'))['risk_limits']).model_dump()
c=Controller(store,risk_limits=risk,clock=clock,can_write=lambda:True,directory=HERE/'native-rehearsal-v2');c.directory.mkdir(exist_ok=True)
before=copy.deepcopy(c.engine.state['profiles']);sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame',clock=clock)
# Reconcile original prospective forecasts against independently replayed proof;
# this is a replay of actual captured chain evidence, never a fixture settlement.
path=c.directory/'recorded-spx';shutil.copytree(HERE/'native-spx2',path,dirs_exist_ok=False)
proof=replay(path);original=json.load(open(path/'bundle.json'))['forecast'];fid=original['id'];binding=c.bindings[fid];now=clock()
store.append(NativePayout44(id=digest(['v44-rehearsal-proof',proof['proof_sha256']]),timestamp=now,available_at=now,source='neraium-poly/read-only-replay/v44',forecast_id=fid,forecast_sha256=digest(original),original_study_sha256=binding['study_sha256'],directory=path.name,verified=True,reason='actual_finalized_chain_bundle_replay',proof=proof))
reports=[]
for cycle in range(3):
 for attempt in range(5):
  sampler.observe()
  try:frame=sampler.latest();break
  except ValueError:
   if attempt==4:raise
   time.sleep(2)
 fees={}
 for row in store.original.latest('FeeObservation',128):
  token=row['token_id']
  if token not in fees:
   p=replay_fee({'evidence_id':row['id']},store,token_id=token,as_of=clock())
   if p['status']=='verified_current_protocol_curve':fees[token]=p
 if cycle==0:
  c.tick(frame,fees,proofs={},frame_provider=sampler.latest)
  proofs=asyncio.run(collect(c.native_bound,store,c.directory,clock=clock,can_write=lambda:True,max_requests=0))
 report=c.tick(frame,fees,proofs=proofs,frame_provider=sampler.latest);reports.append(report);time.sleep(2)
assert c.engine.state['profiles']['aggressive']['suspended']==before['aggressive']['suspended']
assert c.engine.state['profiles']['aggressive']['cash']==before['aggressive']['cash']
assert all(c.engine.state['profiles'][n]['closed'][:len(s['closed'])]==s['closed'] for n,s in before.items())
result={'scope':'isolated local state; actual current reference snapshots and archived finalized chain proof; not deployed/account fills','sampler':sampler.status(),'report':reports[-1]}
(HERE/'rehearsal-v2.json').write_text(json.dumps(result,indent=2)+'\n')
r=reports[-1];print(json.dumps({k:r[k] for k in ('cycles','markets_evaluated_unique','forecasts','parent_events','verified_outcomes','event_group_scores')},indent=2))
print('new cohort', {n:{k:p[k] for k in ('open_positions','pending_orders','cash_hypothetical')} for n,p in r['phase44_cohort']['profiles'].items()})
