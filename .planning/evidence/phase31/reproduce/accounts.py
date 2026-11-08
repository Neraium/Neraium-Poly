import datetime,hashlib,json,pathlib,sqlite3,sys
root=pathlib.Path('/home/ubuntu/Neraium-Poly');phase=sys.argv[1];out=root/'.planning/evidence/phase31'
result={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'accounts':{},'tables':{}}
pre=json.loads((out/'accounts-before.json').read_text()) if phase=='after' else None
for account in ['paper-live','experimental-paper']:
 for name in ['risk.sqlite','broker.sqlite']:
  c=sqlite3.connect(f'file:{root}/data/{account}/{name}?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('BEGIN');check=c.execute('PRAGMA quick_check').fetchall();assert [r[0] for r in check]==['ok']
  for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
   if table.startswith('sqlite_'):continue
   rows=[list(r) for r in c.execute('SELECT * FROM "'+table+'" ORDER BY 1')];key=account+'/'+name+'/'+table
   digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest();result['tables'][key]={'rows':len(rows),'sha256':digest}
   if pre and (account=='paper-live' or table in ('audit','experimental_registry')):
    n=pre['tables'][key]['rows'];assert len(rows)>=n;assert hashlib.sha256(json.dumps(rows[:n],sort_keys=True).encode()).hexdigest()==pre['tables'][key]['sha256'],key
  if name=='risk.sqlite':
   a=dict(c.execute('SELECT * FROM account WHERE id=1').fetchone());result['accounts'][account]={'cash':a['cash'],'realized_pnl':a['realized'],'emergency_stop':bool(a['kill']),'limits':json.loads(a['limits']),'positions':c.execute('SELECT count(*) FROM positions').fetchone()[0]}
  c.close()
result['preexisting_table_prefixes_verified']=bool(pre)
(out/f'accounts-{phase}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['accounts'],indent=2))
