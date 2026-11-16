"""Compact read-only operation sample; no order, reset or deployment interface."""
import json,sqlite3,subprocess,shutil,time
from pathlib import Path
from datetime import UTC,datetime
import httpx
ROOT=Path('/home/ubuntu/Neraium-Poly')
UNITS=[('neraium-poly-paper.service',18742,1024**3),('neraium-poly-experimental.service',18743,2*1024**3)]

def sample(with_operations=False):
    result={'at':datetime.now(UTC).isoformat(),'disk_free_bytes':shutil.disk_usage(ROOT).free,'services':{},'accounts':{},'unsafe':[]}
    if result['disk_free_bytes']<100*1024**3:result['unsafe'].append('filesystem_floor')
    for unit,port,limit in UNITS:
        fields=['MainPID','NRestarts','ActiveState','SubState','MemoryCurrent','MemoryPeak','MemoryMax','CPUQuotaPerSecUSec','TasksMax','ActiveEnterTimestampMonotonic']
        data=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit]+[v for f in fields for v in ['-p',f]],text=True).splitlines())
        base=Path('/sys/fs/cgroup/system.slice')/unit
        for file in ['memory.events','cpu.stat']:
            try:data[file]={k:int(v) for k,v in (line.split() for line in (base/file).read_text().splitlines())}
            except OSError:pass
        pid=data['MainPID']; proc=Path('/proc')/pid
        try:
            data['rss_bytes']=next(int(line.split()[1])*1024 for line in (proc/'status').read_text().splitlines() if line.startswith('VmRSS:'))
            data['io']={k.rstrip(':'):int(v) for k,v in (line.split() for line in (proc/'io').read_text().splitlines())}
            flags={}
            for item in (proc/'environ').read_bytes().split(b'\0'):
                k,_,v=item.partition(b'=')
                if k in (b'PAPER_TRADING',b'LIVE_TRADING_ENABLED'):flags[k.decode()]=v.decode()
            data['mode_flags']=flags
            if flags!={'PAPER_TRADING':'true','LIVE_TRADING_ENABLED':'false'}:result['unsafe'].append(unit+':mode')
        except (OSError,StopIteration):data['process_read_error']=True
        if int(data['MemoryMax'])!=limit or data['CPUQuotaPerSecUSec']!='1s' or int(data['TasksMax'])!=(64 if port==18742 else 32):result['unsafe'].append(unit+':limits')
        try:
            start=time.monotonic();response=httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=2,trust_env=False)
            response.raise_for_status();data['health']=response.json();data['health_latency_seconds']=time.monotonic()-start
            if data['health'].get('live_trading_enabled') is not False or data['health'].get('paper_trading') is not True:result['unsafe'].append(unit+':health_mode')
        except Exception as error:data['health_error']=type(error).__name__
        if with_operations and 'health' in data:
            try:
                start=time.monotonic();response=httpx.get(f'http://127.0.0.1:{port}/api/operations-state',timeout=4,trust_env=False)
                response.raise_for_status();op=response.json();data['operations_latency_seconds']=time.monotonic()-start
                archive=op.get('archive',{})
                data['archive']={k:archive.get(k) for k in ['health','last_error','usage_bytes','budget_bytes','free_bytes','global_floor_bytes','segments','sealed_segments','compressed_segments','records','measurement_at','cold_verification','growth_bytes_per_second','seconds_to_exhaustion']}
                data['connectivity']=op.get('operation',{}).get('connectivity')
                watcher=op.get('operations_research',{}).get('phase26',{}).get('inputs') or {}
                watcher=watcher.get('watcher') or {}
                data['supplemental']={k:watcher.get(k) for k in ['status','subscribed_tokens','qualified_books','last_qualified_at','last_error','quarantined_tokens','identity_quarantine_saturated','counts','transport']}
                data['memory_sampler']=op.get('memory',op.get('operation',{}).get('memory',{})).get('latest')
                data['research_io']=op.get('research_io');data['independent_weather_research']=op.get('independent_weather_research')
            except Exception as error:data['operations_error']=type(error).__name__
        result['services'][unit]=data
    for account in ['paper-live','experimental-paper']:
        db=sqlite3.connect(f'file:{ROOT/"data"/account/"risk.sqlite"}?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row;db.execute('BEGIN')
        r=dict(db.execute('select cash,realized,kill,limits from account where id=1').fetchone());r['limits_sha256']=__import__('hashlib').sha256(r.pop('limits').encode()).hexdigest()
        r['positions']=db.execute('select count(*) from positions').fetchone()[0];r['reservations']=db.execute('select count(*) from reservations where released=0').fetchone()[0];db.close()
        db=sqlite3.connect(f'file:{ROOT/"data"/account/"broker.sqlite"}?mode=ro',uri=True,timeout=2);r['orders']=db.execute('select count(*) from orders').fetchone()[0];db.close()
        if r['positions'] or r['reservations'] or r['orders']!=(13 if account=='experimental-paper' else 0) or r['kill']!=(account=='experimental-paper') or abs(r['cash']-(496.11522059829053 if account=='experimental-paper' else 500))>1e-8:result['unsafe'].append(account+':capital_or_stop')

        if r['limits_sha256']!='5d49295ce5df09ad48cda10e3f9fe2eadc5ce793ea741e0070a05f4eca00a6b0':result['unsafe'].append(account+':risk_limits_changed')
        result['accounts'][account]=r
    return result
