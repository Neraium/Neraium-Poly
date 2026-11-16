"""Reproduce the bounded production result, not a backtest or profit claim."""
import json
import statistics
from datetime import datetime
from pathlib import Path

P=Path(__file__).resolve().parent
post=json.loads((P/'admission-activation/postflight.json').read_text());r=post['report']

def window(path):
    result=json.loads((path/'result.json').read_text());rows=[json.loads(x) for x in (path/'samples.jsonl').read_text().splitlines()]
    active=[v for v in rows if v['elapsed']>=result['ready_after_seconds']];unique={v['research']['as_of']:v['research'] for v in active if v.get('research',{}).get('as_of')};values=list(unique.values());residual=[]
    for old,new in zip(values,values[1:]):residual.append((datetime.fromisoformat(new['as_of'])-datetime.fromisoformat(old['as_of'])).total_seconds()-new['shadow_worker']['cycle_seconds']-5)
    fresh=sum(v.get('research',{}).get('status')=='fresh' for v in active)
    return {'post_ready_seconds':result['post_ready_seconds'],'samples':len(active),'fresh_samples':fresh,'fresh_fraction':fresh/len(active),'unique_updates':len(unique),
        'median_worker_seconds':statistics.median(v['shadow_worker']['cycle_seconds'] for v in values),'median_scheduling_residual_seconds':statistics.median(residual),
        'median_health_api_seconds':statistics.median(v['latency'] for v in active if 'latency' in v),'peak_cgroup_memory_bytes':result['peak_memory_bytes']}

profiles={}
for name,v in r['profiles'].items():
    profiles[name]={**v,'order_intents':sum(s['orders'] for s in v['strategies'].values()),'modeled_fill_events':sum(s['fill_events'] for s in v['strategies'].values()),
        'modeled_exit_net_pnl':sum(s['modeled_exit_net_pnl'] for s in v['strategies'].values()),'verified_native_settlement_net_pnl':sum(s['verified_settlement_net_pnl'] for s in v['strategies'].values()),
        'candidate_screens':sum(s['candidates'] for s in v['strategies'].values()),'candidate_count_is_repeated_screens_not_independent_opportunities':True}
accounts={name:{'cash':v['risk.sqlite']['account']['cash'],'historical_realized_pnl':v['risk.sqlite']['account']['realized'],'stop_latched':bool(v['risk.sqlite']['account']['kill']),
    'positions':v['risk.sqlite']['positions'],'unreleased_reservations':v['risk.sqlite']['reservations'],'historical_broker_orders':v['broker.sqlite']['orders']} for name,v in post['postflight']['accounts'].items()}
result={'as_of':r['as_of'],'source':post['source'],'pid':post['pid'],'reference_pid':'355170','branch':'citadel/phase42-continuous-shadow','markets_evaluated_unique':r['markets_evaluated_unique'],
    'fixed_calibration_cohort_forecasts':r['forecasts'],'recent_source_forecast_records_cached':r['current_source_forecasts'],'native_parent_events':r['parent_events'],
    'reviewed_independent_groups':0,'verified_outcomes':r['verified_outcomes'],'scores':r['scores'],'calibration_improvement_established':False,'profiles':profiles,'accounts':accounts,
    'before':window(P/'research-activation/observation'),'after':window(P/'admission-activation/observation'),'archive':post['archive']['archive'],
    'paper_only':True,'actual_new_broker_orders':0,'actual_new_broker_fills':0,'automatic_restarts':0,'oom_kills':0,'intentional_experimental_restarts':4,'reference_restarted':False,'rollback_executed':False,
    'profitability_demonstrated':False,'limits':['three mutually exclusive500USD scenarios; never add their returns/capital','modeled bid exits are not exchange fills or native settlement','source forecast repetitions are not independent events','unknown fees and slippage/redemption reserves remain assumptions','sequential450s live windows are not identical controlled traffic','remaining stale snapshots withheld','cgroup memory includes reclaimable file cache; short observation is not proof of indefinite stability']}
(P/'results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('source','pid','markets_evaluated_unique','fixed_calibration_cohort_forecasts','native_parent_events','before','after')}))
