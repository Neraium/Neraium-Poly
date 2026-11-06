"""Independently replay genuine checkpoint studies through read-only SQLite handles."""
import datetime,hashlib,json,pathlib,sqlite3,time
from neraium_poly.research.phase16.continuous import ContinuousQualification
from neraium_poly.research.phase14.relationships import digest
root=pathlib.Path('/home/ubuntu/Neraium-Poly');base=root/'data/experimental-paper'
def read(p):
 c=sqlite3.connect(f'file:{p}?mode=ro',uri=True,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c
cat=read(base/'events-archive.sqlite');records=cat.execute("SELECT * FROM records WHERE kind='QualificationStudy' ORDER BY available_at DESC,id DESC LIMIT 64").fetchall();cat.close();rows=[];total=0
for r in records:
 p=base/'events-segments'/r['segment'];c=read(p);s=c.execute('SELECT kind,payload,digest FROM events WHERE id=?',(r['id'],)).fetchone();c.close()
 assert s['kind']==r['kind'] and s['digest']==r['digest'] and hashlib.sha256(s['payload'].encode()).hexdigest()==r['digest'];total+=len(s['payload']);assert total<64*1024**2;rows.append(json.loads(s['payload']))
class ReadOnlySnapshot:
 def latest(self,kind,limit=100):assert kind=='QualificationStudy';return rows[:limit]
start=time.monotonic();study=ContinuousQualification(ReadOnlySnapshot());assert study.last_id==rows[0]['id'] and digest(study._state())==rows[0]['checkpoint_sha256']
value={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_records':len(rows),'source_payload_bytes':total,'full_checkpoints':sum(r['full_checkpoint'] is not None for r in rows),'newest_study_id':study.last_id,'source_row_sha256':records[0]['digest'],'restored_checkpoint_sha256':digest(study._state()),'source_model_sha256':study.code_sha256,'replay_exact':True,'mode':'native SQLite read-only/query_only; no EventStore owner, no ledger/service writes','seconds':time.monotonic()-start,'summary':study.summary()}
(root/'data/phase16/live-recovery.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k!='summary'},indent=2))
