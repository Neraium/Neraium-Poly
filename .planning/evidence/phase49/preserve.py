"""Read-only ledger measurements and original evidence checks."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase35.native import replay_native_directory
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase47.cohort import FROZEN
from neraium_poly.research.phase47.storage import read

root = Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
native = root / 'phase42-native'
admin = root / 'native-migration48'
sha = lambda data: hashlib.sha256(data).hexdigest()
plan = json.loads((admin / 'plan.json').read_bytes())
result = {'observed_at': datetime.now(UTC).isoformat(), 'ledgers': {}, 'backup_sha256': sha((admin / 'original-native.tar.gz').read_bytes()), 'plan_sha256': digest(plan)}
assert result['backup_sha256'] == 'f6c44edd1dbb5801d67b2905f0646186bf8707ee999991f38d96e822b6077671'
for name, expected in plan['files'].items():
    path = native/name
    raw = read(path) if expected['compress'] else path.read_bytes()
    assert len(raw) == expected['bytes'] and sha(raw) == expected['sha256'], name
for name, proof_hash in plan['proofs'].items():
    path = native/name
    bundle = json.loads(read(path/'bundle.json'))
    proof = replay_native_directory(path) if 'parent_event' in bundle else replay(path)
    assert digest(proof) == proof_hash
result['original_files'] = len(plan['files'])
result['original_proofs'] = len(plan['proofs'])
for name in ('event-intelligence', 'event-intelligence/domains'):
    directory = root/name
    path = directory/'forecasts.sqlite'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('BEGIN')
        rows = db.execute("select kind,count(*),max(json_extract(payload,'$.available_at')) from journal group by kind").fetchall()
        head = db.execute('select seq,chain from journal order by seq desc limit 1').fetchone()
        settings = {'pages':db.execute('pragma page_count').fetchone()[0],'free_pages':db.execute('pragma freelist_count').fetchone()[0]}
        sizes = {p.name:p.stat().st_size for p in directory.glob('forecasts.sqlite*')}
    result['ledgers'][name] = {'bytes_by_file':sizes,'bytes':sum(sizes.values()),'cap_bytes':64*1024**2,'remaining_bytes':64*1024**2-sum(sizes.values()),'by_kind':rows,'head':head,**settings}
archive = ReadonlyArchive(root)
result['frozen_trials'] = {}
for fid in FROZEN:
    raw = archive.get(fid)[1]
    trial = json.loads(raw)
    assert digest(trial['source_forecast']) == trial['source_binding']['forecast_sha256']
    result['frozen_trials'][fid] = sha(raw.encode())
Path(sys.argv[1]).write_text(json.dumps(result, indent=2)+'\n')
