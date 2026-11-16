"""One sequential, time-bounded audit worker; durable per-batch continuation."""
import json,os,resource,shutil,time
from pathlib import Path
from neraium_poly.data.archive_audit import audit
for name in ('paper-live','experimental-paper'):
    output=Path('.planning/evidence/phase38')/(name+'-integrity.jsonl')
    cursor=''; existing=[]
    if output.exists():
        for line in output.read_text().splitlines():
            r=json.loads(line); existing.append(r)
        if existing: cursor=existing[-1]['next_after']
    start=time.monotonic()
    if existing and existing[-1].get('range_complete'): continue
    with output.open('a') as handle:
        while time.monotonic()-start < 600:
            if shutil.disk_usage('.').free < 100*1024**3: break
            r=audit(Path('data')/name,after=cursor,max_segments=128,max_seconds=60)
            r['audit_process_maxrss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
            handle.write(json.dumps(r,sort_keys=True)+'\n');handle.flush();os.fsync(handle.fileno())
            if r['status']=='failed' or r['next_after']==cursor: break
            cursor=r['next_after']
            if r.get('range_complete'): break
