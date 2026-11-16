"""Summarize frozen service observation; no trading or deployment interface."""
import json
import math
import sys
from pathlib import Path

folder=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent
rows=[json.loads(line) for line in (folder/'samples.jsonl').read_text().splitlines()]
rows=[r for r in rows if r['stage']=='observation']
assert rows and not any(r['critical'] for r in rows)
first,last=rows[0],rows[-1];seconds=last['elapsed_seconds']-first['elapsed_seconds']
def distribution(values):
    v=sorted(values)
    return {k:v[max(0,math.ceil(len(v)*p)-1)] for k,p in [('median',.5),('p95',.95),('p99',.99),('maximum',1)]} if v else None

result={'observation':json.loads((folder/'result.json').read_text()),'counter_window_seconds':seconds,
    'first_at':first['at'],'last_at':last['at'],'services':{},'accounts_start':first['accounts'],
    'accounts_end':last['accounts'],'disk_free_bytes':last['disk_free_bytes'],'no_safety_incident':True}
for unit in first['services']:
    start,end=first['services'][unit],last['services'][unit]
    data=[r['services'][unit] for r in rows]
    q={'pid':end['MainPID'],'pid_unchanged':all(d['MainPID']==start['MainPID'] for d in data),
        'automatic_restarts_delta':int(end['NRestarts'])-int(start['NRestarts']),
        'oom_kills_delta':end.get('memory.events',{}).get('oom_kill',0)-start.get('memory.events',{}).get('oom_kill',0),
        'cgroup_memory_bytes':{'min':min(int(d['MemoryCurrent']) for d in data),'max':max(int(d['MemoryCurrent']) for d in data)},
        'rss_bytes':{'min':min(d.get('rss_bytes',0) for d in data),'max':max(d.get('rss_bytes',0) for d in data)},
        'health_roundtrip_seconds':distribution([d['health_latency_seconds'] for d in data if 'health_latency_seconds' in d]),
        'operations_roundtrip_seconds':distribution([d['operations_latency_seconds'] for d in data if 'operations_latency_seconds' in d]),
        'ingestion_age_seconds':distribution([d['health']['last_ingestion_age_seconds'] for d in data if d.get('health',{}).get('last_ingestion_age_seconds') is not None]),
        'cpu_core_equivalents':(end.get('cpu.stat',{}).get('usage_usec',0)-start.get('cpu.stat',{}).get('usage_usec',0))/1e6/seconds,
        'health_status_counts':{s:sum(d.get('health',{}).get('status')==s for d in data) for s in ('ok','degraded')},
        'archive_end':end.get('archive')}
    if start.get('archive') and end.get('archive'):
        q['archive_growth_bytes_per_second']=(end['archive']['usage_bytes']-start['archive']['usage_bytes'])/seconds
        q['new_sealed_segments']=end['archive']['sealed_segments']-start['archive']['sealed_segments']
        q['new_compressed_segments']=end['archive']['compressed_segments']-start['archive']['compressed_segments']
    a=(start.get('supplemental') or {}).get('transport');b=(end.get('supplemental') or {}).get('transport')
    if a is not None and b is not None:
        keys=('reconnects','queue_overflows','queue_backpressure_waits','queue_backpressure_seconds','queue_backpressure_timeouts','consumer_events','messages','native_books_delivered','invalidations','gaps')
        q['supplemental_counter_deltas']={k:b[k]-a[k] for k in keys}
        active=[r for r in rows if (r['services'][unit].get('supplemental') or {}).get('subscribed_tokens',0)]
        active_seconds=last['elapsed_seconds']-active[0]['elapsed_seconds'] if active else 0
        q.update(supplemental_active_window_seconds=active_seconds,supplemental_activation_sample_at=active[0]['at'] if active else None,
            supplemental_reconnects_per_hour=q['supplemental_counter_deltas']['reconnects']*3600/active_seconds if active_seconds else None,
            supplemental_queue_peak_depth=b['queue_peak_depth'],supplemental_consumer_max_seconds=b['consumer_max_seconds'],
            final_supplemental=end['supplemental'],fresh_supplemental_samples=sum(d.get('supplemental',{}).get('qualified_books',0)>0 for d in data),
            supplemental_active_samples=len(active))
    result['services'][unit]=q
baseline=json.loads(Path('/home/ubuntu/Neraium-Poly/.planning/evidence/phase38-activation/summary.json').read_text())
result['phase38_comparison']={'counter_window_seconds':baseline['effective_counter_window_seconds'],
    'experimental':baseline['services']['neraium-poly-experimental.service']}
result['limitations']=['Different genuine market traffic/cohorts; normalized rates are descriptive, not a matched causal experiment.',
    'Supplemental discovery startup is excluded from active-stream rate denominator, with 30-second sampling uncertainty.',
    'HTTP roundtrip includes client/dispatch overhead, not an internal event-loop lag measurement.',
    'Cold verification reports are reused; no repeated complete historical archive audit.',
    'This bounded observation does not establish indefinite reliability or profitability.']
(folder/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'duration':result['observation'],'services':{u:{k:v for k,v in d.items() if k in ('pid','oom_kills_delta','automatic_restarts_delta','supplemental_counter_deltas','supplemental_active_window_seconds','supplemental_queue_peak_depth','supplemental_consumer_max_seconds','fresh_supplemental_samples','supplemental_active_samples','health_roundtrip_seconds')} for u,d in result['services'].items()}},indent=2))
