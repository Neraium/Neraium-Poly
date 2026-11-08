import json,time,resource
from pathlib import Path
from datetime import datetime,UTC
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase25 import finance
from neraium_poly.research.phase27.forecasting import spx_observations,evaluate_payout_challenger,fit_payout_posterior
import sys
root=Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve();manifest=json.loads((root/'.planning/evidence/phase25/reconciliation-delivery.json').read_text());entry=next(f for f in manifest['forecasts'] if f['scope']=='phase25_expansion' and f['model_version'].startswith('spx-'))
with ReadonlyArchive(root/'data/experimental-paper') as reader:
 kind,payload,sha=reader.get(entry['original_record_id']);study=json.loads(payload);f=next(x for x in study['forecasts'] if x['id']==entry['forecast_id']);byid={e['id']:e for e in study['evidence']};evidence=[byid[k] for k in f['evidence_ids']]
now=datetime.now(UTC);assert finance.replay(f,evidence,as_of=now)['verified']
rows=spx_observations(evidence,cutoff=now);start=time.monotonic()
try:evaluate_payout_challenger(rows)
except ValueError as error:causal_block=str(error)
else:raise AssertionError('old availability cannot be accepted as point-in-time')
result=evaluate_payout_challenger(rows,reconstructed=True)
result.update(observed_at=now.isoformat(),source={'original_record_id':study['id'],'original_record_payload_sha256':sha,'original_forecast_id':f['id'],'raw_source_sha256':evidence[0]['payload']['raw_response_sha256'],'provider':evidence[0]['provider'],'url':evidence[0]['source'],'retrieved_at':evidence[0]['retrieved_at'],'original_source_model_replayed':True,'available_source_rows':len(rows)},strict_point_in_time_rejection=causal_block,elapsed_seconds=time.monotonic()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,prospective_model_fit=fit_payout_posterior(rows,cutoff=now,weekday=f['contract']['target_weekday']))
Path('.planning/evidence/phase27-forecast/authentic-spx-evaluation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['source','split','calibration_weight','heldout_squared_payout_error_improvement','block_bootstrap_interval_95','elapsed_seconds']}));print('metrics',result['global_frequency_baseline']['squared_payout_error'],result['weekday_raw']['squared_payout_error'],result['weekday_calibrated']['squared_payout_error'])
