"""Read-only activation gate; never opens an account/archive as a writer."""
import hashlib,json,sqlite3,subprocess,shutil
from pathlib import Path
from datetime import UTC,datetime
from threading import RLock
import httpx
from neraium_poly.risk import RiskLimits
from neraium_poly.research.phase12.ledger import EventForecastLedger
from neraium_poly.research.phase13.runtime import SportsForecastJournal
SOURCE='1342482fd9431f4e2e69d8788d864cb32fd1d4e9'
ROOT=Path('/home/ubuntu/Neraium-Poly')

def inspect(full=False):
    checks=[];out={'at':datetime.now(UTC).isoformat(),'expected_source':SOURCE,'accounts':{},'services':{},'disk_free_bytes':shutil.disk_usage(ROOT).free}
    checks.append(out['disk_free_bytes']>100*1024**3)
    out['source_match']=subprocess.run(['git','diff','--quiet',SOURCE,'--','backend','tests','frontend','config','pyproject.toml','uv.lock']).returncode==0
    checks.append(out['source_match'])
    for account,cfgpath in [('paper-live','config/paper-live.example.json'),('experimental-paper','config/experimental-paper.example.json')]:
        config=json.load(open(cfgpath));expected=RiskLimits(**config['risk_limits']).model_dump();a={}
        checks.append(config['archive_budget_mb']==153600 and config['archive_reserve_disk_mb']==102400)
        for name in ['risk.sqlite','broker.sqlite','service.sqlite']:
            p=ROOT/'data'/account/name;db=sqlite3.connect(f'file:{p}?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row
            db.execute('PRAGMA cache_size=-4096');db.execute('BEGIN');r={}
            if full:r['quick_check']=db.execute('pragma quick_check').fetchone()[0];checks.append(r['quick_check']=='ok')
            if name=='risk.sqlite':
                row=dict(db.execute('select * from account where id=1').fetchone());row['limits']=json.loads(row['limits']);r['account']=row
                r['positions']=db.execute('select count(*) from positions').fetchone()[0];r['reservations']=db.execute('select count(*) from reservations where released=0').fetchone()[0]
                r['fills']=db.execute("select count(*) from audit where action in ('fill','experimental_exit_fill')").fetchone()[0]
                checks += [row['limits']==expected,r['positions']==0,r['reservations']==0,row['kill']==(account=='experimental-paper')]
                checks.append(abs(row['cash']-(496.11522059829053 if account=='experimental-paper' else 500))<1e-8)
            if name=='broker.sqlite':
                r['orders']=db.execute('select count(*) from orders').fetchone()[0]
                r['open_orders']=db.execute("select count(*) from orders where json_extract(report,'$.status') in ('open','partial')").fetchone()[0]
                checks += [r['orders']==(13 if account=='experimental-paper' else 0),r['open_orders']==0]
            if name=='service.sqlite':
                rows=db.execute('select key,payload,digest from state').fetchall();r['hashes_valid']=all(hashlib.sha256(x['payload'].encode()).hexdigest()==x['digest'] for x in rows);checks.append(r['hashes_valid'])
            db.close();a[name]=r
        out['accounts'][account]=a
    for unit,port,limit,tasks in [('neraium-poly-paper.service',18742,1024**3,64),('neraium-poly-experimental.service',18743,2*1024**3,32)]:
        names=['MainPID','NRestarts','ActiveState','ActiveEnterTimestamp','MemoryCurrent','MemoryPeak','MemoryMax','CPUQuotaPerSecUSec','TasksMax','WorkingDirectory','ExecStart','FragmentPath','DropInPaths']
        args=['systemctl','show',unit]+[v for n in names for v in ['-p',n]]
        fields=dict(line.split('=',1) for line in subprocess.check_output(args,text=True).splitlines())
        pid=fields['MainPID'];flags={}
        for item in Path('/proc',pid,'environ').read_bytes().split(b'\0'):
            key,_,value=item.partition(b'=')
            if key in (b'PAPER_TRADING',b'LIVE_TRADING_ENABLED'):flags[key.decode()]=value.decode()
        fields['flags']=flags
        checks += [flags=={'PAPER_TRADING':'true','LIVE_TRADING_ENABLED':'false'},int(fields['MemoryMax'])==limit,fields['CPUQuotaPerSecUSec']=='1s',int(fields['TasksMax'])==tasks]
        try:fields['health']=httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=4,trust_env=False).json()
        except Exception as e:fields['health_error']=type(e).__name__
        out['services'][unit]=fields
    if full:
        out['journals']={}
        for path,cls in [('data/experimental-paper/event-intelligence/forecasts.sqlite',EventForecastLedger),('data/experimental-paper/event-intelligence/domains/forecasts.sqlite',EventForecastLedger),('data/experimental-paper/event-intelligence/sports/prospective.sqlite',SportsForecastJournal)]:
            obj=cls.__new__(cls);obj._lock=RLock();obj.max_records=100000;obj.db=sqlite3.connect(f'file:{(ROOT/path).resolve()}?mode=ro',uri=True,timeout=3);obj.db.row_factory=sqlite3.Row;obj.db.execute('BEGIN');out['journals'][path]=obj.verify();obj.db.close()
    out['safety_passed']=all(checks)
    return out
if __name__=='__main__':
    result=inspect(full=True);print(json.dumps(result,sort_keys=True,indent=2));raise SystemExit(0 if result['safety_passed'] else 2)
