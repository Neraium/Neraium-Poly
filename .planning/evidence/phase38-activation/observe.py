"""Bounded post-activation sampling and automatic halt; never resumes admission."""
import json,os,subprocess,time
from pathlib import Path
from sample import sample
root=Path('.planning/evidence/phase38-activation')
expected=json.load(open(root/'observation-pids.json'))
duration=900;start=time.monotonic();bad={u:0 for u in expected};count=0;status='completed'
with (root/'observation.jsonl').open('a') as out:
    while time.monotonic()-start < duration:
        began=time.monotonic();row=sample(with_operations=True);row['elapsed_seconds']=time.monotonic()-start;row['stage']='post_activation';critical=list(row['unsafe'])
        for unit,pid in expected.items():
            data=row['services'][unit];health=data.get('health',{})
            if data['MainPID']!=pid or int(data['NRestarts']) or data.get('memory.events',{}).get('oom_kill',0):critical.append(unit+':restart_or_oom')
            bad[unit]=bad[unit]+1 if health.get('status')!='ok' else 0
            if bad[unit]>=3:critical.append(unit+':persistent_unhealthy')
            archive=data.get('archive',{})
            if archive.get('health')=='blocked' or archive.get('last_error'):critical.append(unit+':archive_integrity_or_capacity')
            if unit.endswith('paper.service') and health.get('trading_status') not in (None,'validation_blocked'):critical.append(unit+':unexpected_admission_state')
        row['critical']=critical;out.write(json.dumps(row,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno());count+=1
        if critical:
            status='halted';(root/'observation-incident.json').write_text(json.dumps(row,sort_keys=True,indent=2)+'\n')
            # Stop only the two authorized services. Preserve all financial state
            # and emergency latches; no restart, source rollback or risk restore.
            halted=subprocess.run(['sudo','-n','systemctl','--no-block','stop',*expected],capture_output=True,text=True,timeout=10)
            (root/'safety-halt.json').write_text(json.dumps({'returncode':halted.returncode,'stdout':halted.stdout,'stderr':halted.stderr})+'\n')
            break
        time.sleep(max(0,30-(time.monotonic()-began)))
result={'status':status,'samples':count,'elapsed_seconds':time.monotonic()-start,'configured_maximum_seconds':duration,'maximum_authorized_seconds':8*3600,'pids':expected,'stop_reset':False,'order_admission_resumed':False}
(root/'observation-result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(result));raise SystemExit(0 if status=='completed' else 2)
