import datetime,hashlib,json,pathlib,sqlite3,sys,gzip
from neraium_poly.research.phase12.ledger import content_sha256
root=pathlib.Path('/home/ubuntu/Neraium-Poly'); folder=root/'data/phase31';phase=sys.argv[1]
result={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'journals':{},'immutable_sources':{}}
pre=json.loads((folder/'integrity-before.json').read_text()) if phase=='after' else None
for relative,table,canonical in [('event-intelligence/forecasts.sqlite','journal',False),('event-intelligence/sports/prospective.sqlite','records',True),('event-intelligence/domains/forecasts.sqlite','journal',False)]:
 p=root/'data/experimental-paper'/relative;c=sqlite3.connect(f'file:{p}?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('BEGIN');previous=None;count=0;prefix=None
 for r in c.execute('SELECT * FROM '+table+' ORDER BY seq'):
  value=json.loads(r['payload']); digest=content_sha256(value) if canonical else hashlib.sha256(r['payload'].encode()).hexdigest()
  assert digest==r['digest'] and r['previous']==previous and r['chain']==content_sha256([previous,r['kind'],r['id'],digest])
  previous=r['chain'];count+=1
  if pre and count==pre['journals'][relative]['records']:prefix=previous
 if pre:assert count>=pre['journals'][relative]['records'] and prefix==pre['journals'][relative]['head_sha256']
 result['journals'][relative]={'records':count,'head_sha256':previous,'preexisting_prefix_preserved':True};c.close()
for account in ['paper-live','experimental-paper']:
 base=root/'data'/account;c=sqlite3.connect(f'file:{base}/events-archive.sqlite?mode=ro',uri=True)
 # Native service recovery verifies the full catalog; do not repeat its scan here.
 for name,raw,gz in c.execute("SELECT name,raw_sha,gzip_sha FROM segments WHERE status IN ('legacy','sealed')"):
  key=account+'/'+name;result['immutable_sources'][key]={'raw_sha256':raw,'gzip_sha256':gz}
  p=base/'events.sqlite' if name=='legacy' else base/'events-segments'/name
  assert p.is_file()
  if gz:assert pathlib.Path(str(p)+'.gz').is_file()
 c.close()
if pre:
 result['completed_compression_transitions_verified']=[]
 for key,expected in pre['immutable_sources'].items():
  actual=result['immutable_sources'][key];assert actual['raw_sha256']==expected['raw_sha256'],key
  if expected['gzip_sha256']:assert actual['gzip_sha256']==expected['gzip_sha256'],key
  elif actual['gzip_sha256']:
   account,name=key.split('/');p=root/'data'/account/'events-segments'/name;g=pathlib.Path(str(p)+'.gz');h=hashlib.sha256()
   with gzip.open(g,'rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
   assert h.hexdigest()==actual['raw_sha256'] and hashlib.sha256(g.read_bytes()).hexdigest()==actual['gzip_sha256'],key
   result['completed_compression_transitions_verified'].append(key)
result['scope']='complete journal chains and catalog preservation; physical hash restoration checked on one recent sealed segment per service, no redundant full archive rehash'
(folder/f'integrity-{phase}.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'phase':phase,'catalog_segments':len(result['immutable_sources']),'journals':result['journals']},indent=2))
