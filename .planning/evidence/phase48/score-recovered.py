"""Existing production settlement logic on an isolated overlay; no live publication.
Original forecasts/positions and financial databases remain unchanged.
"""
import copy,json
from datetime import UTC,datetime
from pathlib import Path
from neraium_poly.data import EventStore
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase44.outcomes import rebind
from neraium_poly.research.phase45.cohort import Explorer
from neraium_poly.research.phase46.program import Program
from neraium_poly.risk import RiskLimits
HERE=Path(__file__).resolve().parent
class Overlay:
 def __init__(self):self.original=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper');self.local=EventStore(HERE/'recovered-settlement.sqlite')
 def get(self,key):return self.local.get(key) or self.original.get(key)
 def latest(self,kind,limit=100):
  rows={r['id']:r for r in [*self.original.latest(kind,limit),*self.local.latest(kind,limit)]};return sorted(rows.values(),key=lambda r:(r['available_at'],r['id']),reverse=True)[:limit]
 def append(self,row):
  if (HERE/'recovered-settlement.sqlite').stat().st_size>64*1024**2:raise ValueError('isolated64MiB bound')
  return self.local.append(row)
store=Overlay();clock=lambda:datetime.now(UTC);risk=RiskLimits(**json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits']).model_dump()
program=Program(store,clock,lambda:True);explorer=Explorer(store,risk_limits=risk,clock=clock,can_write=lambda:True);before=copy.deepcopy(explorer.state);proofs={};verified=[]
for row in json.loads((HERE/'frozen-native-recovery.json').read_text())['results']:
 if not row.get('verified'):continue
 p=replay(HERE/row['directory']);assert p==row['proof'];trial=program.rows[row['trial_id']];f=trial['source_forecast'];assert digest(f)==row['source_forecast_sha256'];proofs[f['id']]=p;verified.append(row['trial_id'])
 for fid,other in explorer.state['forecasts'].items():
  try:proofs[fid]=rebind(p,f,other)
  except ValueError:continue
program.settle(proofs);explorer.settle(proofs)
for n,s in before['profiles'].items():assert explorer.state['profiles'][n]['closed'][:len(s['closed'])]==s['closed']
report={'at':clock().isoformat(),'scope':'ISOLATED production-code replay; live research journal, accounts and positions NOT modified; results await safe activation/publication','verified_frozen_trials':verified,'program':program.report(),'explorer':explorer.report(),'new_native_closes':{n:s['closed'][len(before['profiles'][n]['closed']):] for n,s in explorer.state['profiles'].items()},'all_in_costs_verified':False,'entry_costs':'original recorded modeled costs retained; native payout verified, historical fee and slippage assumptions not upgraded','profitable_edge_demonstrated':False,'reviewed_independent_samples':0,'local_records':store.local.replay()}
(HERE/'recovered-scoring.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ('verified_frozen_trials','new_native_closes','profitable_edge_demonstrated')}))
store.local.close()
