"""Reproduce Phase46 comparisons from retained, timestamped real observations."""
import json
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent

def read(path):return json.loads((HERE/path).read_text())
def samples(path):
    p=HERE/path
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else json.loads((p.parent/'compact-samples.json').read_text())
def metrics(rows):
    valid=[r for r in rows if r.get('health',{}).get('status')=='ok' and r.get('research',{}).get('reference_feed')]
    # Comparable post-recovery300s windows, not startup errors mixed with ready operation.
    start=valid[0]['elapsed'];rows=[r for r in rows if r['elapsed']>=start];research=[r['research'] for r in rows if r.get('research',{}).get('cycles',0)>0]
    cycles={r['as_of']:r['shadow_worker']['cycle_seconds'] for r in research if r.get('shadow_worker')};durations=list(cycles.values())
    return {'samples':len(rows),'duration_seconds':rows[-1]['elapsed']-rows[0]['elapsed'],'fresh_research':sum(r.get('research',{}).get('status')=='fresh' for r in rows),
            'unique_completed_cycles':len(cycles),'median_cycle_seconds':statistics.median(durations) if durations else None,'maximum_cycle_seconds':max(durations) if durations else None,
            'peak_memory_bytes':max(int(r['service']['MemoryCurrent']) for r in rows),'maximum_api_latency':max((r['latency'] for r in rows if 'latency' in r),default=None),
            'automatic_restarts':rows[-1]['service']['NRestarts'],'oom_kills':rows[-1]['memory_events']['oom_kill']}

pre=read('pre-observation/result.json');post=read('activation-fix/postflight.json');report=post['report'];before=pre['final']['research'];strategies={};deltas={}
for name,path in (('legacy',None),('phase44','phase44_cohort'),('phase45','phase45_explorer')):
    current=report[path] if path else report;old=before[path] if path else before
    strategies[name]={};deltas[name]={}
    for profile,p in current['profiles'].items():
        strategies[name][profile]={'strategies':p['strategies'],'unrealized':p['unrealized_net_pnl'],'drawdown':p['maximum_drawdown'],'suspended':p['suspended'],'open_positions':p['open_positions']}
        deltas[name][profile]={s:{k:v[k]-old['profiles'][profile]['strategies'][s][k] for k in ('screened_observations','unique_enrolled_opportunities','orders','fill_events','modeled_exit_net_pnl','verified_settlement_net_pnl')} for s,v in p['strategies'].items()}
candidates=report['phase45_explorer']['economic_candidates']
summary={'source':post['source'],'pid':post['pid'],'before':metrics(samples('pre-observation/samples.jsonl')),'after':metrics(samples('activation-fix/observation/samples.jsonl')),
         'indexed_forecasts':report['forecasts'],'native_inventory':report['native_outcome_inventory'],'outcome_program':report['outcome_program'],'event_group_scores':report['event_group_scores'],
         'baseline_warning':'all22 legacy labels were zero; zero-predictor Brier0/logloss0, one-predictor Brier1/clipped logloss27.631; no independently validated model superiority',
         'markets_evaluated_unique_cumulative':report['phase45_explorer']['markets_evaluated_unique'],'new_market_ids':report['phase45_explorer']['markets_evaluated_unique']-before['phase45_explorer']['markets_evaluated_unique'],
         'rejection_delta_observations':{name:{k:v['observations'].get(k,0)-before['phase45_explorer']['rejection_breakdown'][name]['observations'].get(k,0) for k in v['observations']} for name,v in report['phase45_explorer']['rejection_breakdown'].items()},'rejection_breakdown':report['phase45_explorer']['rejection_breakdown'],'strategy_deltas':deltas,'strategies':strategies,
         'loss_attribution':{k:(report[v] if v else report)['loss_attribution']['by_strategy'] for k,v in (('legacy',None),('phase44','phase44_cohort'),('phase45','phase45_explorer'))},
         'current_fee_coverage':report['current_fee_coverage'],'native_pricing_contracts':report['phase45_explorer']['native_pricing_contracts'],'native_reconciliation':report['native_reconciliation'],'source_refresh':report.get('source_refresh'),
         'current_economics':{'rows':len(candidates),'positive_conditional_net':sum(c['estimated_net_profit']>0 for c in candidates),'positive_uncertainty_lower_net':sum(c.get('uncertainty_lower_net_profit') is not None and c['uncertainty_lower_net_profit']>0 for c in candidates),
                              'all_in_cost_verified':sum(c['all_in_costs_verified'] for c in candidates),'best_hypotheses':candidates[:3],'status':'conditional model estimates, not verified profitability'},
         'positions':report['positions'],'unfilled_orders':report['unfilled_orders'],'archive':post['archive'],'postflight_safety_passed':post['postflight']['safety_passed'],
         'reference_pid_unchanged':post['postflight']['services']['neraium-poly-paper.service']['MainPID']=='555731','stop_latched':post['postflight']['accounts']['experimental-paper']['risk.sqlite']['account']['kill']==1,
         'rollback_executed':False,'qualification':'no real-account order access, no certified promotion; paper/shadow outcomes remain separate from financial performance'}
(HERE/'closing.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('source','pid','before','after','indexed_forecasts','native_inventory','new_market_ids','current_economics')},indent=2))
