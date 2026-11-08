import sqlite3,pathlib,json,time,gzip,hashlib,tempfile,datetime,sys
OUTPUT=pathlib.Path(sys.argv[1]);
if OUTPUT.exists():raise ValueError("new output path required")
pathlib.Path("data/phase33-storage").mkdir(parents=True,exist_ok=True)
from neraium_poly.data import EventStore
from neraium_poly.research.phase28.continuous import VolumeStudy
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase33.storage import pack_dense_checkpoint
root=pathlib.Path('/home/ubuntu/Neraium-Poly/data/experimental-paper');names=json.loads(pathlib.Path('.planning/evidence/phase33-storage/benchmark.json').read_text())['source_segments'];inputs=[]
for name in names:
 c=sqlite3.connect(f'file:{root}/events-segments/{name}?mode=ro',uri=True)
 for row in c.execute("SELECT id,kind,available_at,event_time,payload,digest FROM events WHERE kind='VolumeStudy'"):
  assert hashlib.sha256(row[4].encode()).hexdigest()==row[5];inputs.append(row)
 c.close()
folder=pathlib.Path(tempfile.mkdtemp(prefix='benchmark-',dir='data/phase33-storage'));old=EventStore(folder/'before.sqlite');new=EventStore(folder/'after.sqlite');count=0;cpu=0;payload_before=payload_after=0;logical=[]
for rid,kind,available,event,payload,sha in inputs:
 value=json.loads(payload);assert value['report'].get('codec') is None
 old._append_payload(rid,kind,available,event,payload);before=VolumeStudy.model_validate(value);frame=unpack_checkpoint(value['decision_frame'])
 start=time.process_time();packed=pack_dense_checkpoint(frame);row=before.model_copy(update={'decision_frame':packed});newpayload=row.model_dump_json();cpu+=time.process_time()-start
 assert digest(json.loads(newpayload))==digest(row.model_dump(mode='json'))
 assert unpack_checkpoint(packed)==frame and row.report==value['report']
 assert new.append(row);count+=1;payload_before+=len(payload.encode());payload_after+=len(newpayload.encode());logical.append(digest(row.report))
old.close();new.close();stats={}
for label,name in [('before','before.sqlite'),('after','after.sqlite')]:
 p=folder/name;stream=hashlib.sha256();gz=pathlib.Path(str(p)+'.gz')
 with p.open('rb') as source,gz.open('wb') as target:
  with gzip.GzipFile(fileobj=target,mode='wb',filename='',mtime=0,compresslevel=6) as z:
   for b in iter(lambda:source.read(1024*1024),b''):stream.update(b);z.write(b)
 with gzip.open(gz,'rb') as z:
  recovered=hashlib.sha256()
  for b in iter(lambda:z.read(1024*1024),b''):recovered.update(b)
 assert recovered.hexdigest()==stream.hexdigest()
 stats[label]={'sqlite_bytes':p.stat().st_size,'additional_cold_gzip_bytes':gz.stat().st_size,'retain_both_total_bytes':p.stat().st_size+gz.stat().st_size,'restored_sha256':recovered.hexdigest()}
 # Reopen only the disposable controlled benchmark DB, not an active service DB.
 c=sqlite3.connect(f'file:{p}?mode=ro',uri=True);rows=c.execute('SELECT payload,digest FROM events ORDER BY available_at,event_time,id').fetchall();c.close()
 restored=[]
 for body,sha in rows:
  assert hashlib.sha256(body.encode()).hexdigest()==sha;restored.append(digest(VolumeStudy.model_validate_json(body).report))
 stats[label]['decoded_reports']=len(restored);stats[label]['logical_report_hashes']=sorted(restored)
assert stats['before']['logical_report_hashes']==stats['after']['logical_report_hashes']
for value in stats.values():value.pop('logical_report_hashes')
r={'observed_at':datetime.datetime.now(datetime.UTC).isoformat(),'scope':'identical genuine archived VolumeStudy inputs, isolated benchmark SQLite with same ledger schema; not live-runway or full-archive claim','records':count,'source_segments':names,'canonical_report_hashes':sorted(logical),'payload_bytes_before':payload_before,'payload_bytes_after':payload_after,'new_dense_encoding_cpu_seconds':cpu,'statistics':stats,'physical_total_saving_fraction':1-stats['after']['retain_both_total_bytes']/stats['before']['retain_both_total_bytes'],'local_controlled_artifact_directory':str(folder),'original_service_sources':'read_only_no_rewrite_no_delete_no_migration','peak_transient_upper_bound_description':'One logical record/frame decoded at a time; existing8MiBraw/2MiBencoded codec ceilings remain. Benchmark retains both closedSQLite and verifiedgzip, no temp deletion.'}
OUTPUT.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
