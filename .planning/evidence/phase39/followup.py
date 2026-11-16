"""Read-only Phase38 follow-up. No service management or stop/reset interface."""
import json,os,sys,time
sys.path.insert(0,'/home/ubuntu/Neraium-Poly/.planning/evidence/phase38-activation')
from sample import sample
start=time.monotonic()
with open('.planning/evidence/phase39/live-followup.jsonl','a') as out:
    while time.monotonic()-start<600:
        began=time.monotonic();row=sample(with_operations=True);row['elapsed_seconds']=time.monotonic()-start
        out.write(json.dumps(row,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno())
        if row['unsafe']:raise SystemExit('Read-only observation halted; safety findings preserved, services unchanged')
        time.sleep(max(0,30-(time.monotonic()-began)))
