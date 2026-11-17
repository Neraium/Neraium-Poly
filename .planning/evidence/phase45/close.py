"""Compact closing evidence from immutable records and completed observation."""
import hashlib
import json
import math
from collections import Counter,defaultdict
from datetime import UTC,datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase45.diagnostics import breakdown

HERE=Path(__file__).resolve().parent;activation=HERE/'activation-repair';source='202da2f502d94ea44d70e5fdcbeb29bae0f2f771'
post=json.loads((activation/'postflight.json').read_text());observation=json.loads((activation/'observation/result.json').read_text());assert post['source']==source
archive=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
def checkpoint(kind):
 row=archive.latest(kind,1)[0];state=unpack_checkpoint(row['checkpoint']);assert digest(state)==row['state_sha256']
 return row,state
main,ms=checkpoint('StrategyCycle');new,ns=checkpoint('StrategyCycle45')
expected=hashlib.sha256(Path('/home/ubuntu/Neraium-Poly/.deploy/releases',source,'backend/neraium_poly/research/phase42/engine.py').read_bytes()).hexdigest();assert main['policy']['code_sha256']==new['policy']['code_sha256']==expected
labels=[];groups=defaultdict(list)
for fid,p in ms['labels'].items():
 f=ms['forecasts'][fid];labels.append({'forecast_id':fid,'forecast_sha256':digest(f),'model':f['model_id'],'domain':f['domain'],'native_parent':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],'forecast_at':f['timestamp'],'resolved_at':p['resolved_at'],'payout':p['payout'],'proof_sha256':p.get('proof_sha256')})
 market=f.get('market_probability');market=f.get('market_expected_payout') if market is None else market
 if p['payout'] not in (0,1) or market is None:continue
 groups[(f['model_id'],f['event_id'])].append((f['probability'],market,p['payout']))
models=defaultdict(list)
for (model,event),rows in groups.items():
 scores={}
 for key,index in [('model',0),('market',1),('neutral',None),('zero_payout_explanatory_baseline',-1)]:
  ps=[min(1-1e-12,max(1e-12,.5 if index is None else 0 if index==-1 else v[index])) for v in rows];ys=[v[2] for v in rows]
  scores[key]={'brier':sum((p-y)**2 for p,y in zip(ps,ys,strict=True))/len(rows),'log_loss':-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys,strict=True))/len(rows)}
 models[model].append({'native_parent':event,'forecast_labels':len(rows),'scores':scores})
performance={}
for model,rows in models.items():
 performance[model]={'native_parent_ids':len(rows),'forecast_labels':sum(r['forecast_labels'] for r in rows),'equal_parent_weighted_scores':{key:{metric:sum(r['scores'][key][metric] for r in rows)/len(rows) for metric in ('brier','log_loss')} for key in rows[0]['scores']},'confidence_interval':None,'reviewed_independent_groups':0}
samples=[json.loads(l) for l in (activation/'observation/samples.jsonl').read_text().splitlines()];ready=next(r['elapsed'] for r in samples if r.get('ready_elapsed'));valid=[r for r in samples if r['elapsed']>=ready]
cycles=[r['research']['shadow_worker']['cycle_seconds'] for r in valid if r.get('research',{}).get('shadow_worker')];cycles.sort()
prior=json.loads((activation/'prior-cohort.json').read_text());baseline=json.loads((HERE/'baseline.json').read_text())['research']
result={'at':datetime.now(UTC).isoformat(),'source':source,'branch':'citadel/phase45-edge','pid':post['pid'],'ci_run':44028184197,
 'unique_phase45_markets':len(ns['markets_seen']),'new_market_ids_after_repair':len(set(ns['markets_seen'])-set(prior['markets_seen'])),'indexed_forecasts':len(ms['forecasts']),'forecast_native_parent_ids':len({f['event_id'] for f in ms['forecasts'].values()}),
 'native_labels':len(labels),'new_native_labels_since_baseline':len(labels)-baseline['verified_outcomes'],'native_parent_ids':len({f['native_parent'] for f in labels}),'labels_by_domain':dict(Counter(f['domain'] for f in labels)),'positive_payout_labels':sum(f['payout']==1 for f in labels),
 'reviewed_independent_training':0,'reviewed_independent_heldout':0,'independence_limitation':'BTC/ETH barriers within the same date are correlated; native parent IDs are not certified independent groups; completion conditioning remains possible',
 'event_weighted_performance':performance,'baseline_limitation':'zero-payout score is a retrospective explanatory check, not a prospectively registered champion or fitted calibration',
 'strategies':post['report']['phase45_explorer'],'legacy_profiles':post['report']['profiles'],'probability_panel':post['report']['probability_panel'],
 'rejections_by_profile':{n:breakdown(p['rejects']) for n,p in ns['profiles'].items()},'exact_rejections':{n:p['rejects'] for n,p in ns['profiles'].items()},
 'observation':{'ready_seconds':observation['ready_after_seconds'],'post_ready_seconds':observation['post_ready_seconds'],'samples':len(valid),'fresh':sum(r.get('research',{}).get('status')=='fresh' for r in valid),'worker_median_seconds':cycles[len(cycles)//2] if cycles else None,'worker_max_seconds':max(cycles) if cycles else None,'accounts_unchanged':observation['accounts_unchanged'],'no_automatic_restarts':True,'experimental_oom_kills':0},
 'cost_limitations':'native fee curves can be verified; entry reserves0.002USD/share and non-native-exit slippage0.0015USD/share remain modeled; all-in costs and probability calibration are not verified; positive central estimates are not conservative profits',
 'qualified_paper_opportunities':0,'demonstrated_profitable_strategies':0,'labels':labels,'archive':post['archive'],'disk_free_GiB':post['postflight']['disk_free_bytes']/1024**3}
(HERE/'results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('source','pid','unique_phase45_markets','indexed_forecasts','native_labels','native_parent_ids','labels_by_domain','observation','disk_free_GiB')},indent=2))
