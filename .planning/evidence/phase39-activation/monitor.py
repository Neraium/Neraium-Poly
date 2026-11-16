"""Bounded startup and 15-minute observation; rollback only experimental source."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,'/home/ubuntu/Neraium-Poly/.planning/evidence/phase38-activation')
from sample import sample

pre=json.loads((HERE/'preflight.json').read_text())
reference_pid=pre['services']['neraium-poly-paper.service']['MainPID']
experimental_pid=subprocess.check_output(['systemctl','show','neraium-poly-experimental.service','-p','MainPID','--value'],text=True).strip()
started=time.monotonic();ready=None;good=0;bad=0;samples=0
with (HERE/'samples.jsonl').open('a') as out:
    while True:
        began=time.monotonic();row=sample(with_operations=True);row['elapsed_seconds']=began-started
        row['stage']='observation' if ready else 'startup'
        critical=list(row['unsafe']);e=row['services']['neraium-poly-experimental.service'];r=row['services']['neraium-poly-paper.service']
        if r['MainPID']!=reference_pid:critical.append('reference_pid_changed')
        if e['MainPID']!=experimental_pid or int(e['NRestarts']):critical.append('experimental_restart')
        if e.get('memory.events',{}).get('oom_kill',0):critical.append('experimental_oom_kill')
        archive=e.get('archive',{})
        if archive.get('last_error') or archive.get('health')=='blocked':critical.append('experimental_archive_failure')
        healthy=e.get('health',{}).get('status')=='ok' and e.get('health',{}).get('public_feed',{}).get('status')=='ok' and archive.get('health')=='ok'
        good=good+1 if healthy else 0
        if ready:
            age=e.get('health',{}).get('last_ingestion_age_seconds')
            bad=bad+1 if not healthy or age is None or age>60 else 0
            if bad>=3:critical.append('persistent_primary_ingestion_failure')
        elif good>=2:
            ready=time.monotonic();(HERE/'ready.json').write_text(json.dumps(row,indent=2)+'\n')
        elif time.monotonic()-started>1500:critical.append('startup_timeout')
        row['critical']=critical;out.write(json.dumps(row,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno());samples+=1
        if critical:
            (HERE/'incident.json').write_text(json.dumps(row,indent=2)+'\n')
            subprocess.run([sys.executable,str(HERE/'rollback.py'),'--execute'],check=True,timeout=120)
            raise SystemExit('Safety halt; source-only rollback started, verify recovery separately')
        if ready and time.monotonic()-ready>=900:break
        time.sleep(max(0,30-(time.monotonic()-began)))
result={'status':'completed','startup_seconds':ready-started,'observation_seconds':time.monotonic()-ready,'samples':samples,'experimental_pid':experimental_pid,'reference_pid':reference_pid,'source':'57b75a50f78d8df93ac15c06deaf626c255deb6b','stop_reset':False,'order_admission_resumed':False}
(HERE/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
