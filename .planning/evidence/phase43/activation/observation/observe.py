"""Bounded readonly operational/shadow observation. Never clears a stop or orders."""
import hashlib
import json
import sqlite3
import subprocess
import time
from datetime import UTC,datetime
from pathlib import Path

import httpx

HERE=Path(__file__).resolve().parent
ROOT=Path('/home/ubuntu/Neraium-Poly');UNIT='neraium-poly-experimental.service';SOURCE='6f0032a71e64fd91d9cc51d9f8910d579c40c58f'

def system(unit):
    fields=['MainPID','ActiveState','NRestarts','MemoryCurrent','MemoryMax','CPUQuotaPerSecUSec','CPUUsageNSec']
    return dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit]+[a for k in fields for a in ('-p',k)],text=True,timeout=5).splitlines())

def account(name):
    root=ROOT/'data'/name;db=sqlite3.connect((root/'risk.sqlite').as_uri()+'?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row;db.execute('BEGIN')
    r=dict(db.execute('select cash,realized,kill,limits from account where id=1').fetchone());r['limits_sha256']=hashlib.sha256(r.pop('limits').encode()).hexdigest();r['positions']=db.execute('select count(*) from positions').fetchone()[0];r['reservations']=db.execute('select count(*) from reservations where released=0').fetchone()[0];db.close()
    db=sqlite3.connect((root/'broker.sqlite').as_uri()+'?mode=ro',uri=True,timeout=2);r['orders']=db.execute('select count(*) from orders').fetchone()[0];db.close();return r

def get(client,path):
    response=client.get('http://127.0.0.1:18743'+path);response.raise_for_status();return response.json()

initial={n:account(n) for n in ('paper-live','experimental-paper')};assert initial['experimental-paper']['kill']==1
samples=[];started=time.monotonic();ready=None;incident=None;pid=system(UNIT)['MainPID']
try:
    with httpx.Client(timeout=5,trust_env=False) as client:
        while time.monotonic()-started<1500:
            row={'at':datetime.now(UTC).isoformat(),'elapsed':time.monotonic()-started,'service':system(UNIT)}
            flags=dict(v.split(b'=',1) for v in Path('/proc',pid,'environ').read_bytes().split(b'\0') if b'=' in v)
            assert flags[b'NERAIUM_DEPLOYED_SOURCE'].decode()==SOURCE and flags[b'NERAIUM_SHADOW_RESEARCH']==b'true'
            assert flags[b'PAPER_TRADING']==b'true' and flags[b'LIVE_TRADING_ENABLED']==b'false'
            assert row['service']['MainPID']==pid and row['service']['ActiveState']=='active' and row['service']['NRestarts']=='0'
            assert row['service']['MemoryMax']==str(2*1024**3) and row['service']['CPUQuotaPerSecUSec']=='1s'
            assert system('neraium-poly-paper.service')['MainPID']=='355170'
            events=Path('/sys/fs/cgroup/system.slice',UNIT,'memory.events').read_text();row['memory_events']=dict(l.split() for l in events.splitlines());assert row['memory_events']['oom_kill']=='0'
            try:
                t=time.monotonic();row['health']=get(client,'/api/health');row['latency']=time.monotonic()-t
                row['research']=get(client,'/api/shadow-research')
                if row['health']['status']=='ok' and row['research'].get('cycles',0)>525 and row['research'].get('exit_tournament'):
                    if ready is None:ready=time.monotonic();row['ready_elapsed']=ready-started
                else:row['withheld']=True
            except httpx.HTTPError as error:row['api_error']=type(error).__name__
            if not samples or len(samples)%6==0:
                row['accounts']={n:account(n) for n in initial};assert row['accounts']==initial
            samples.append(row)
            with (HERE/'samples.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
            if ready is None and time.monotonic()-started>600:raise ValueError('startup recovery/API did not become ready within600s')
            if ready is not None and time.monotonic()-ready>=360:break
            time.sleep(5)
    final={n:account(n) for n in initial};assert final==initial
    valid=[r for r in samples if r.get('research',{}).get('cycles',0)>0]
    assert valid,'no working research observation'
    assert any(r['research'].get('status')=='fresh' for r in valid),'no fresh research snapshots'
    result={'source':SOURCE,'pid':pid,'duration_seconds':time.monotonic()-started,'ready_after_seconds':ready-started if ready else None,'post_ready_seconds':time.monotonic()-ready if ready else 0,
        'samples':len(samples),'fresh_research_samples':sum(r.get('research',{}).get('status')=='fresh' for r in samples),'final':valid[-1],
        'peak_memory_bytes':max(int(r['service']['MemoryCurrent']) for r in samples),'accounts_unchanged':True,'accounts':final,'rollback_executed':False}
    (HERE/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('final','accounts')}))
except Exception as error:
    (HERE/'incident.json').write_text(json.dumps({'error':str(error),'pid':pid,'last':samples[-1] if samples else None},indent=2)+'\n');raise
