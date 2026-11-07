"""Bounded preregistered source capture; reads original Phase16 records, never owner DBs."""
import datetime,hashlib,json,pathlib,sqlite3,time
root=pathlib.Path('/home/ubuntu/Neraium-Poly');base=root/'data/experimental-paper';out=root/'data/phase17/capture';out.mkdir(exist_ok=True);protocol=json.loads((root/'data/phase17/protocol.json').read_text());end=datetime.datetime.fromisoformat(protocol['cutoff']);start=datetime.datetime.now(datetime.timezone.utc);seen=set();total=0;records=[]
def read(p):
 c=sqlite3.connect(f'file:{p}?mode=ro',uri=True,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c
while True:
 cat=read(base/'events-archive.sqlite');rows=cat.execute("SELECT * FROM records WHERE kind='QualificationStudy' ORDER BY available_at DESC,id DESC LIMIT ?",(128 if not seen else 8,)).fetchall();cat.close()
 for r in reversed(rows):
  if r['id'] in seen:continue
  at=datetime.datetime.fromisoformat(r['available_at'])
  if at>end:continue
  p=base/'events-segments'/r['segment'];c=read(p);v=c.execute('SELECT kind,payload,digest FROM events WHERE id=?',(r['id'],)).fetchone();c.close();assert v and v['kind']==r['kind'] and v['digest']==r['digest'] and hashlib.sha256(v['payload'].encode()).hexdigest()==r['digest'];body=v['payload'].encode();total+=len(body);assert total<=protocol['storage_limit_bytes'];name=r['id']+'.json'
  with (out/name).open('xb') as f:f.write(body)
  seen.add(r['id']);records.append({'id':r['id'],'kind':r['kind'],'path':name,'sha256':r['digest'],'available_at':r['available_at'],'source_segment':r['segment'],'bytes':len(body)})
 manifest={'protocol_sha256':hashlib.sha256((root/'data/phase17/protocol.json').read_bytes()).hexdigest(),'started_at':start.isoformat(),'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'records':records,'bytes':total,'native_catalog_and_payload_hashes_verified':True,'source':'original live Phase16QualificationStudy, not fixtures/replay/current substituted quotes','max_bytes':protocol['storage_limit_bytes'],'completed':datetime.datetime.now(datetime.timezone.utc)>=end}
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 if datetime.datetime.now(datetime.timezone.utc)>=end:break
 time.sleep(min(10,max(0,(end-datetime.datetime.now(datetime.timezone.utc)).total_seconds())))
print(json.dumps({'records':len(records),'bytes':total,'started_at':start.isoformat(),'ended_at':manifest['updated_at'],'protocol_sha256':manifest['protocol_sha256']}))
