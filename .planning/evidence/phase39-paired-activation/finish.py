"""Final read-only source/account/journal checks; run after bounded observation."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx

HERE=Path(__file__).resolve().parent
ROOT=Path('/home/ubuntu/Neraium-Poly')
result=json.loads((HERE/'result.json').read_text())
assert result['status']=='completed' and result['observation_seconds']>=900
env={**os.environ,'PYTHONPATH':str(ROOT/'backend')}
checked=subprocess.run([sys.executable,str(ROOT/'.planning/evidence/phase38-activation/guard.py')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
(HERE/'postflight.json').write_text(checked.stdout)
assert checked.returncode==0, checked.stderr
post=json.loads(checked.stdout);assert post['safety_passed']
assert all(v['health']['status']=='ok' for v in post['services'].values())
assert all(v['integrity']=='verified' for v in post['journals'].values())
manifest=json.loads((HERE/'release-manifest.json').read_text());release=Path(manifest['release'])
assert all(hashlib.sha256((release/name).read_bytes()).hexdigest()==sha for name,sha in manifest['files'].items())
pid=post['services']['neraium-poly-experimental.service']['MainPID'];assert pid==result['experimental_pid']
flags={}
for item in Path('/proc',pid,'environ').read_bytes().split(b'\0'):
    key,_,value=item.partition(b'=')
    if key in (b'NERAIUM_DEPLOYED_SOURCE',b'PAPER_TRADING',b'LIVE_TRADING_ENABLED',b'PYTHONPATH'):flags[key.decode()]=value.decode()
assert flags['NERAIUM_DEPLOYED_SOURCE']==manifest['source']
assert flags['PYTHONPATH']==str(release/'backend')
assert post['services']['neraium-poly-paper.service']['MainPID']==result['reference_pid']=='355170'
anchors=json.loads((HERE.parent/'phase39-activation'/'preflight.json').read_text())['journals'];prefixes={}
for name,anchor in anchors.items():
    db=sqlite3.connect((ROOT/name).as_uri()+'?mode=ro',uri=True,timeout=3)
    table='records' if 'sports/' in name else 'journal'
    row=db.execute(f'SELECT chain FROM {table} WHERE seq=?',(anchor['records'],)).fetchone();db.close()
    assert row and row[0]==anchor['head_sha256'];prefixes[name]=True
sys.path.insert(0,str(release/'backend'))
from neraium_poly.research.phase17.provenance import ReadonlyArchive
with ReadonlyArchive(ROOT/'data/experimental-paper') as reader:audit=reader.latest('PairedRecoveryAudit',1)[0]
assert audit['result']['scan_complete'] and audit['result']['snapshot_guard_bytes']==64*1024**2
assert not audit['trading_authority'] and not audit['certification_authority']
assert audit['result']['recovery_code_sha256']==manifest['files']['backend/neraium_poly/research/phase39/recovery.py']
op=httpx.get('http://127.0.0.1:18743/api/operations-state',timeout=5,trust_env=False).json();research=op['operations_research']
assert research['phase20'].get('runtime_error') is None and research['phase20'].get('last_error') is None
final={'source':manifest['source'],'pid':pid,'process_source_flags':flags,'manifest_verified_files':len(manifest['files']),
    'reference_pid':'355170','reference_source':'1342482fd9431f4e2e69d8788d864cb32fd1d4e9','journal_prefixes_preserved':prefixes,
    'recovery_audit':audit,'phase20':research['phase20'],'phase28_counts':research.get('phase28',{}).get('counts'),
    'sampler':{k:research['phase26']['inputs'].get(k) for k in ('sampling_error','sampling_task_active','sampling_queue','counts')},
    'rollback_executed':False,'stop_reset':False,'order_admission_resumed':False}
(HERE/'final-attestation.json').write_text(json.dumps(final,indent=2)+'\n');print(json.dumps({'source':manifest['source'],'pid':pid,'safety_passed':True,'prefixes_preserved':True,'paired_recovery_error':None}))
