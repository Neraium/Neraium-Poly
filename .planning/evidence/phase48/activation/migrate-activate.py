"""Quiescent, backed-up, reversible native-only migration then source activation.
Financial files never restored. Only experimental service managed.
"""
import hashlib,json,os,shutil,subprocess,tarfile,tempfile
from datetime import UTC,datetime
from pathlib import Path
import deploy
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase48.migration import Migration,allocation,snapshot,syncdir,live_guard
HERE=Path(__file__).resolve().parent
ROOT=deploy.ROOT/'data/experimental-paper/phase42-native'
JOURNAL=ROOT.parent/'native-migration48'
assert not (HERE/'migration-live.json').exists(),'activation already attempted; inspect exact checkpoint before resuming'
gate=deploy.gate(full=True);(HERE/'immediate-gate.json').write_text(json.dumps(gate,indent=2)+'\n')
assert deploy.DROP.read_bytes()==(HERE/'current-source.conf').read_bytes()
manifest=json.loads((HERE/'release-manifest.json').read_text());assert deploy.files(deploy.RELEASE)==manifest['files']
assert json.loads((HERE/'rollback-ready.json').read_text())['source_only']
rehearsal=json.loads((HERE.parent/'migration-rehearsal.json').read_text());assert rehearsal['interrupted_then_resumed'] and rehearsal['restoration_byte_exact']
subprocess.run(['sudo','-n','systemctl','stop',deploy.UNIT],check=True,timeout=90)
live_guard()
initial=snapshot(ROOT)
preserved=json.loads((HERE.parent/'ending-native-identities.json').read_text())['snapshot']
assert initial['files']==preserved['files'] and initial['proofs']==preserved['proofs'],'original Phase48 manifest differs; keep stopped and inspect'
assert initial['implementation_sha256']==hashlib.sha256(Path(__import__('neraium_poly.research.phase48.migration',fromlist=['__file__']).__file__).read_bytes()).hexdigest()
# All logical source objects must match the fully verified rehearsal before any mutation.
assert len(initial['files'])==rehearsal['isolated_original_files'] and initial['proofs']==rehearsal['original_proof_identities']
source=ReadonlyArchive(ROOT.parent);anchors={}
for row in source.latest('NativePayout44',512):
 if row['verified'] and row['directory'] in initial['proofs']:
  assert digest(row['proof'])==initial['proofs'][row['directory']];anchors[row['directory']]=row['id']
assert set(anchors)==set(initial['proofs'])
JOURNAL.mkdir(exist_ok=True)
backup=JOURNAL/'original-native.tar.gz'
assert not backup.exists(),'preserve existing backup; inspect recovery checkpoint'
with tarfile.open(backup,'w:gz',compresslevel=6) as tar:tar.add(ROOT,arcname='native')
with backup.open('rb') as f:os.fsync(f.fileno())
syncdir(JOURNAL)
with tempfile.TemporaryDirectory(prefix='verify-backup-',dir=JOURNAL) as tmp:
 with tarfile.open(backup) as tar:tar.extractall(tmp,filter='data')
 assert snapshot(Path(tmp)/'native')==initial,'backup bytes, identities or proofs changed'
backup_sha=hashlib.sha256(backup.read_bytes()).hexdigest()
(HERE/'backup-ready.json').write_text(json.dumps({'at':datetime.now(UTC).isoformat(),'path':str(backup),'sha256':backup_sha,'bytes':backup.stat().st_size,'all_original_files_verified':len(initial['files']),'all_proofs_verified':len(anchors),'reference_pid':deploy.command('systemctl','show','neraium-poly-paper.service','-p','MainPID','--value').strip()},indent=2)+'\n')
m=Migration(ROOT,JOURNAL)
try:result=m.migrate();m.verify()
finally:m.close()
result.update({'at':datetime.now(UTC).isoformat(),'backup_sha256':backup_sha,'backup_bytes':backup.stat().st_size,'published_anchors':anchors,'source':deploy.SOURCE,'logical_evidence_deleted':False,'reference_restarted':False,'financial_records_restored':False,'free_bytes':shutil.disk_usage(ROOT).free})
assert result['free_bytes']>100*1024**3
(HERE/'migration-live.json').write_text(json.dumps(result,indent=2)+'\n')
# Rollback's existing Phase47 decoder reads migrated v44 originals by gzip fallback.
# Reversal was independently tested; source-only rollback never replaces newer journals.
assert deploy.command('systemctl','show','neraium-poly-paper.service','-p','MainPID','--value').strip()=='555731'
live_guard()
deploy.command('sudo','-n','install','-m','644',str(HERE/'experimental-source.conf'),str(deploy.DROP))
deploy.command('sudo','-n','systemctl','daemon-reload')
deploy.command('sudo','-n','systemctl','start',deploy.UNIT,timeout=90)
print(json.dumps({'source':deploy.SOURCE,'physical_allocated_reclaimed_bytes':result['before']['allocated_bytes']-result['after']['allocated_bytes'],'backup_bytes':result['backup_bytes'],'native_headroom_bytes':64*1024**2-result['after']['unique_bytes'],'proofs_verified':result['proofs_verified'],'start_requested':True}))
