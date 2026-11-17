"""All retained observations; separate startup, comparable post-ready5min window."""
import json,math,statistics
from pathlib import Path
H=Path(__file__).resolve().parent;E=H.parent;A=E/'activation';O=A/'observation'
def metrics(rows):
 unique={r['research']['as_of']:r['research']['shadow_worker']['cycle_seconds'] for r in rows if r.get('research',{}).get('shadow_worker',{}).get('cycle_seconds') is not None}
 values=sorted(unique.values());lat=sorted(r['latency'] for r in rows if 'latency' in r)
 def quant(v,p):return v[min(len(v)-1,math.ceil(p*len(v))-1)] if v else None
 return {'samples':len(rows),'fresh_reports':sum(r.get('research',{}).get('status')=='fresh' for r in rows),'fresh_percent':100*sum(r.get('research',{}).get('status')=='fresh' for r in rows)/len(rows) if rows else None,'api_errors':sum('api_error'in r for r in rows),'healthy_ingestion_samples':sum(r.get('health',{}).get('status')=='ok' for r in rows),'unique_completed_cycles':len(values),'cycle_seconds_p50':statistics.median(values) if values else None,'cycle_seconds_p95':quant(values,.95),'cycle_seconds_max':max(values) if values else None,'health_api_seconds_p50':statistics.median(lat) if lat else None,'health_api_seconds_p95':quant(lat,.95),'health_api_seconds_max':max(lat) if lat else None,'peak_cgroup_memory_bytes':max((int(r['service']['MemoryCurrent']) for r in rows),default=None),'failed_or_stale_rows_discarded':False}
before=[json.loads(l) for l in (E/'before-observation/samples.jsonl').read_text().splitlines()]
result=json.loads((O/'result.json').read_text());after=[json.loads(l) for l in (O/'samples.jsonl').read_text().splitlines()];ready=result['ready_after_seconds'];post=[r for r in after if r['elapsed']>=ready-1e-6];start=[r for r in after if r['elapsed']<ready-1e-6]
# ready flag is set during that row's HTTP calls, after row.elapsed was captured.
if start and 'ready_elapsed'in start[-1]:post.insert(0,start.pop())
r={'source':result['source'],'ci_run':44162494371,'before':metrics(before),'after_post_ready':metrics(post),'startup':{'duration_seconds':ready,'samples':len(start),'api_errors':sum('api_error'in r for r in start)},'post_ready_duration_seconds':result['post_ready_seconds'],'accounts_unchanged':result['accounts_unchanged'],'method':'Same observe.py, sequential health+research read, 5s sleep, 300s ready window. Failed/stale post-ready rows retained. Startup separated explicitly; no claim of long-term stability or deterministic causality from unmatched changing markets.'}
(H/'comparison.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
