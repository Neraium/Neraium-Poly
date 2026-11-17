"""Derive compact evidence from frozen snapshots; never reacquire or alter data."""
import hashlib
import json
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
comparisons={}
for name in ('activation','activation-repair'):
 root=HERE/name;observed=json.loads((root/'observation/result.json').read_text())
 raw=root/'observation/samples.jsonl';rows=[json.loads(l) for l in raw.read_text().splitlines()];ready=next(r['elapsed'] for r in rows if r.get('ready_elapsed'));post=[r for r in rows if r['elapsed']>=ready];cycles={}
 compact=[]
 for r in post:
  research=r.get('research',{});worker=research.get('shadow_worker',{})
  if worker:cycles[research['cycles']]=worker['cycle_seconds']
  compact.append({'at':r['at'],'elapsed':r['elapsed'],'health':r.get('health',{}).get('status'),'research':research.get('status'),'research_age':research.get('age_seconds'),'error':research.get('runtime_error') or r.get('api_error'),'cycle_id':research.get('cycles'),'cycle_seconds':worker.get('cycle_seconds'),'memory_bytes':int(r['service']['MemoryCurrent']),'oom_kills':int(r['memory_events']['oom_kill']),'automatic_restarts':int(r['service']['NRestarts'])})
 out={k:v for k,v in observed.items() if k not in ('final',)}
 out.update(post_ready_samples=len(post),fresh_post_ready_samples=sum(r.get('research',{}).get('status')=='fresh' for r in post),observed_unique_cycles=len(cycles),median_observed_unique_cycle_seconds=statistics.median(cycles.values()),max_observed_cycle_seconds=max(cycles.values()),source_samples_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),samples=compact,limitation='different live windows and market inputs; no long-term stability or causal profit inference')
 (root/'observation/summary.json').write_text(json.dumps(out,indent=2)+'\n');comparisons[name]={k:out[k] for k in ('post_ready_seconds','post_ready_samples','fresh_post_ready_samples','observed_unique_cycles','median_observed_unique_cycle_seconds','max_observed_cycle_seconds')}
post=json.loads((HERE/'activation-repair/postflight.json').read_text());r=json.loads((HERE/'results.json').read_text())
r['matched_observation_protocol']=comparisons;r['shadow_positions']=[p for p in post['report']['positions'] if p.get('cohort')=='phase45'];r['decision_cards']=[p for p in post['report']['recent_decisions'] if p.get('cohort')=='phase45'];r['shadow_cost_attribution']=post['report']['phase45_explorer']['loss_attribution'];r['conditional_hypotheses']=[]
for t in r['shadow_cost_attribution']['trades']:
 r['conditional_hypotheses'].append({'order_id':t['order_id'],'probability_assumption':t['probability'],'quantity':t['quantity'],'capital':t['entry_cost'],'conditional_expected_net_profit':t['probability']*t['quantity']-t['entry_cost'],'modeled_downside_if_zero_payout':-t['entry_cost'],'fee_curve_verified':t['fee_verified'],'uncertainty':t['uncertainty'],'entry_modeled_fees':t['entry_fees'],'unmodeled_costs_remain':True,'qualified_opportunity':False})
(HERE/'results.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(comparisons,indent=2));print(json.dumps(r['conditional_hypotheses'],indent=2))
