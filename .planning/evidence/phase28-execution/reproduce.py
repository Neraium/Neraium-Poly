"""Read authentic prior prospective evidence; never rewrite it or submit orders."""
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase28.execution import analyze_depth

root=Path(sys.argv[1] if len(sys.argv)>1 else '/home/ubuntu/Neraium-Poly')
source=root/'.planning/evidence/phase27/production-findings.json'
raw=source.read_bytes();record=json.loads(raw);entry=record['new_prospective_payout_estimates'][0];f=entry['forecast']
rows=[]
for fraction in [.1,1.]:
 for fee in [None,0.,.005,.01,.02]:
  report=analyze_depth(f['book'],as_of=f['timestamp'],expected_payout=f['expected_payout'],lower_payout=f['lower_probability'],upper_payout=f['upper_probability'],fee_rate=fee,settlement_cost_per_share=0.,latency_liquidity_fraction=fraction)
  assert report['status']=='conditional_assumption_scenarios'
  rows.append({'assumed_effective_entry_fee_rate':fee,'assumed_settlement_cost_per_share':0.,'assumed_surviving_fraction':fraction,'analysis':report})
result={'observed_at':datetime.now(UTC).isoformat(),'scope':'as-recorded authentic prospective SPX quote and conditional model; replay is not a new forecast, live trade, or verified profit',
        'original_evidence_sha256':hashlib.sha256(raw).hexdigest(),'original_study_id':entry['study_id'],'forecast_id':f['id'],'market_id':f['market_id'],'event_id':f['event_id'],
        'forecast_timestamp':f['timestamp'],'book_timestamp':f['book']['timestamp'],'book_sha256':digest(f['book']),'expected_conditional_payout':f['expected_payout'],
        'source_model_replayed_by_prior_phase':entry['proof']['verified'],'calibration_verified':False,'actual_fees_verified':False,
        'implementation_sha256':hashlib.sha256(Path(__file__).resolve().parents[3].joinpath('backend/neraium_poly/research/phase28/execution.py').read_bytes()).hexdigest(),
        'assumption_scenarios':rows,'genuine_trades':0,'net_profit_observed':None,'research_only':True,'trading_authority':False}
Path('.planning/evidence/phase28-execution/authentic-depth-scenarios.json').write_text(json.dumps(result,indent=2)+'\n')
for row in rows:
 r=row['analysis'];m=r['maximum_point_profit'];print(json.dumps({'survival':row['assumed_surviving_fraction'],'fee_assumption':row['assumed_effective_entry_fee_rate'],'point_quantity':m['quantity'] if m else None,'point_net':m['expected_net_profit'] if m else None,'gross_quantity':r['maximum_gross_profit']['quantity'],'gross_profit':r['maximum_gross_profit']['expected_gross_profit'],'lower_net_max':r['maximum_conservative_positive_net_profit']}))
