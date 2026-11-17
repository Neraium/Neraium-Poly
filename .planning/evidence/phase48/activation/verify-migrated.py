"""Read-only original-manifest and migration-journal verification, live-safe.
Only frozen original paths are replayed; newly acquired directories stay owned
by their bounded native worker. No migration/store constructor or financial writes.
"""
import hashlib,json,sqlite3,gzip
from pathlib import Path
from neraium_poly.research.phase48.migration import allocation,sha,bounded
from neraium_poly.research.phase47.storage import read
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase35.native import replay_native_directory
HERE=Path(__file__).resolve().parent;root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper/phase42-native');admin=root.parent/'native-migration48';plan=json.loads((admin/'plan.json').read_text());original=json.loads((HERE.parent/'ending-native-identities.json').read_text())['snapshot'];assert plan['files']==original['files'] and plan['proofs']==original['proofs']
for name,expected in plan['files'].items():
 raw=read(root/name) if expected['compress'] else bounded(root/name)
 assert len(raw)==expected['bytes'] and sha(raw)==expected['sha256'],name
for name,h in plan['proofs'].items():
 path=root/name;b=json.loads(read(path/'bundle.json'));p=replay_native_directory(path) if 'parent_event' in b else replay(path)
 assert digest(p)==h and p==json.loads(read(path/'proof.json')),name
with sqlite3.connect((admin/'migration.sqlite').as_uri()+'?mode=ro',uri=True) as db:
 assert db.execute('pragma integrity_check').fetchone()[0]=='ok';rows=db.execute("select payload,digest from events order by json_extract(payload,'$.sequence') limit 32769").fetchall()
assert len(rows)<=32768;previous=None;records=[]
for i,(payload,h) in enumerate(rows):
 assert sha(payload.encode())==h;r=json.loads(payload)
 assert r['sequence']==i and r['plan_sha256']==digest(plan) and r['previous_id']==(previous['id'] if previous else None) and r['previous_sha256']==(digest(previous) if previous else None)
 previous=r;records.append(r)
assert records[-1]['operation']=='complete'
raw=json.dumps(records,indent=2).encode();(HERE/'migration-journal.json.gz').write_bytes(gzip.compress(raw,mtime=0));(HERE/'migration-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
backup=admin/'original-native.tar.gz';backup_sha=hashlib.sha256(backup.read_bytes()).hexdigest();assert backup_sha==json.loads((HERE/'backup-ready.json').read_text())['sha256']
admin_allocated=sum(p.stat().st_blocks*512 for p in admin.rglob('*') if p.is_file());migration=json.loads((HERE/'migration-live.json').read_text());reclaimed=migration['before']['allocated_bytes']-migration['after']['allocated_bytes']
result={'original_logical_files_verified':len(plan['files']),'original_native_proofs_replayed':len(plan['proofs']),'original_content_and_proof_hashes_unchanged':True,'plan_sha256':digest(plan),'journal_chain_events_verified':len(rows),'journal_export_decoded_sha256':sha(raw),'backup_sha256':backup_sha,'backup_bytes':backup.stat().st_size,'native_at_migration':migration['after'],'native_current':allocation(root),'migration_native_allocated_reclaimed_bytes':reclaimed,'retained_backup_and_administrative_allocated_bytes':admin_allocated,'net_allocated_savings_after_retained_backup_and_journal_bytes':reclaimed-admin_allocated,'live_source_archives_deleted':False}
(HERE/'migration-integrity.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
