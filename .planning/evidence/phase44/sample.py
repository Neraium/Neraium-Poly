"""120s bounded readonly matched operations sample; no account mutation."""
import json,time,sys,subprocess
from pathlib import Path
from datetime import UTC,datetime
import httpx
out=Path(sys.argv[1]);start=time.monotonic();rows=[]
with httpx.Client(timeout=3,trust_env=False) as c:
 while time.monotonic()-start<120:
  r={'at':datetime.now(UTC).isoformat(),'elapsed':time.monotonic()-start}
  for name,url in [('reference','http://127.0.0.1:18742/api/market-frame'),('health','http://127.0.0.1:18743/api/health'),('research','http://127.0.0.1:18743/api/shadow-research')]:
   t=time.monotonic()
   try:
    res=c.get(url);res.raise_for_status();d=res.json()
    if name=='reference':d={k:d.get(k) for k in ('id','timestamp','available_at','producer_health')}
    elif name=='research':d={k:d.get(k) for k in ('status','as_of','cycles','runtime_error','input_frame_available_at','shadow_worker','forecasts','parent_events','verified_outcomes')}
    r[name]=d
   except httpx.HTTPError as e:r[name]={'error':type(e).__name__}
   r[name+'_seconds']=time.monotonic()-t
  for unit in ('neraium-poly-paper.service','neraium-poly-experimental.service'):
   r[unit]=dict(l.split('=',1) for l in subprocess.check_output(['systemctl','show',unit,'-p','MainPID','-p','MemoryCurrent','-p','CPUUsageNSec','-p','NRestarts'],text=True,timeout=3).splitlines())
  rows.append(r)
  with out.open('a') as f:f.write(json.dumps(r)+'\n')
  time.sleep(max(0,5-(time.monotonic()-start-r['elapsed'])))
print(json.dumps({'samples':len(rows),'fresh':sum(r['research'].get('status')=='fresh' for r in rows),'ref_timeouts':sum('error' in r['reference'] for r in rows),'healthy_ingestion':sum(r['health'].get('status')=='ok' for r in rows)}))
