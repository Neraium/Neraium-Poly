"""Comparable controlled 50,000-row replay, old/new code, disposable fixture."""
import ast,hashlib,json,resource,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
import neraium_poly.data.segmented as m

if len(sys.argv)==1:
    with tempfile.TemporaryDirectory(prefix='np38-replay-') as tmp:
        root=Path(tmp);raw=root/'segment-00000001.sqlite'
        db=sqlite3.connect(raw)
        db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,kind TEXT,available_at TEXT,event_time TEXT,payload TEXT,digest TEXT)')
        cat=sqlite3.connect(root/'events-archive.sqlite')
        cat.executescript('CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,available_at TEXT,event_time TEXT,digest TEXT,segment TEXT,qualified INTEGER); CREATE INDEX records_segment ON records(segment); CREATE TABLE segments(name TEXT PRIMARY KEY, records INTEGER);')
        for i in range(50000):
            rid=hashlib.sha256(str(i).encode()).hexdigest();at='2026-11-16T00:00:00+00:00'
            payload=json.dumps({'id':rid,'timestamp':at,'available_at':at,'source':'CONTROLLED','data':'x'*512})
            digest=hashlib.sha256(payload.encode()).hexdigest()
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(rid,'Fixture',at,at,payload,digest))
            cat.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',(rid,'Fixture',at,at,digest,raw.name,-1))
        cat.execute('INSERT INTO segments VALUES(?,?)',(raw.name,50000));cat.commit();db.commit();db.close();cat.close()
        out={}
        for mode in ('before','after'):
            run=subprocess.run([sys.executable,__file__,mode,tmp],text=True,capture_output=True,timeout=90,check=False)
            out[mode]=json.loads(run.stdout) if run.returncode==0 else {'error':run.stderr}
        print(json.dumps({'kind':'controlled_recovery_fixture','comparison_scope':'same records, full metadata/hash verification; directory-budget traversal excluded in both','results':out}))
else:
    mode,root=sys.argv[1],Path(sys.argv[2]);s=m.ManagedEventStore.__new__(m.ManagedEventStore)
    s.path=root/'events.sqlite';s.catalog_path=root/'events-archive.sqlite'
    s.catalog=sqlite3.connect(s.catalog_path);s.catalog.row_factory=sqlite3.Row;s.catalog.execute('PRAGMA journal_mode=WAL')
    s.catalog.execute('PRAGMA cache_size=-65536');s._check_budget=lambda *a,**k:None
    method=m.ManagedEventStore._index_segment
    if mode=='before':
        tree=ast.parse(subprocess.check_output(['git','show','7e42fee:backend/neraium_poly/data/segmented.py'],text=True))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ManagedEventStore')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_index_segment')
        ns=dict(m.__dict__);exec(compile(ast.Module(body=[fn],type_ignores=[]),'baseline','exec'),ns);method=ns['_index_segment']
    count=[0]
    def trace(sql):
        count[0]+=int('SELECT * FROM records WHERE id=' in sql)
    s.catalog.set_trace_callback(trace)
    start=time.monotonic();records=method(s,root/'segment-00000001.sqlite','segment-00000001.sqlite')
    print(json.dumps({'records':records,'seconds':time.monotonic()-start,'maxrss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'random_record_lookups':count[0]}));s.catalog.close()
