import json,os,time
from pathlib import Path
from sample import sample
root=Path('.planning/evidence/phase38-activation');start=time.monotonic();seen_api=None;good=0
with (root/'reference-startup.jsonl').open('a') as out:
    while time.monotonic()-start<1500:
        row=sample(with_operations=True);ref=row['services']['neraium-poly-paper.service'];row['stage']='reference_startup'
        out.write(json.dumps(row,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno())
        if row['unsafe'] or ref.get('memory.events',{}).get('oom_kill',0) or int(ref['NRestarts'])>0:
            (root/'startup-failure.json').write_text(json.dumps(row,sort_keys=True)+'\n');raise SystemExit(2)
        if ref.get('health') and seen_api is None:seen_api=row['at']
        conn=ref.get('connectivity') or {}
        healthy=ref.get('health',{}).get('status')=='ok'
        healthy=healthy and ref.get('archive',{}).get('health')=='ok' and conn.get('ws_connected') and conn.get('fresh_books',0)>0 and conn.get('native_books_delivered',0)>0 and 'consumer_events' in conn
        good=good+1 if healthy else 0
        if good>=2:
            row.update(first_api_seen_at=seen_api,ready_at=row['at']);(root/'reference-ready.json').write_text(json.dumps(row,sort_keys=True,indent=2)+'\n');print('Reference ready, PID',ref['MainPID'],'RSS',ref.get('rss_bytes'),'fresh_books',conn.get('fresh_books'));raise SystemExit(0)
        time.sleep(10)
raise SystemExit('reference startup deadline exceeded')
