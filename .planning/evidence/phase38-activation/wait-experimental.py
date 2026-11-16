import json,os,time
from pathlib import Path
from sample import sample
root=Path('.planning/evidence/phase38-activation');start=time.monotonic();seen_api=None;good=0
with (root/'experimental-startup.jsonl').open('a') as out:
    while time.monotonic()-start<1500:
        row=sample(with_operations=True);exp=row['services']['neraium-poly-experimental.service'];ref=row['services']['neraium-poly-paper.service'];row['stage']='experimental_startup'
        out.write(json.dumps(row,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno())
        if row['unsafe'] or any(int(s['NRestarts']) or s.get('memory.events',{}).get('oom_kill',0) for s in row['services'].values()):
            (root/'startup-failure.json').write_text(json.dumps(row,sort_keys=True)+'\n');raise SystemExit(2)
        if exp.get('health') and seen_api is None:seen_api=row['at']
        healthy=exp.get('health',{}).get('status')=='ok' and exp.get('health',{}).get('public_feed',{}).get('status')=='ok' and exp.get('archive',{}).get('health')=='ok' and ref.get('health',{}).get('status')=='ok'
        good=good+1 if healthy else 0
        if good>=2:
            row.update(first_api_seen_at=seen_api,ready_at=row['at']);(root/'experimental-ready.json').write_text(json.dumps(row,sort_keys=True,indent=2)+'\n');print('Experimental ready, PID',exp['MainPID'],'RSS',exp.get('rss_bytes'),'ingestion age',exp['health'].get('last_ingestion_age_seconds'));raise SystemExit(0)
        time.sleep(10)
raise SystemExit('experimental startup deadline exceeded')
