"""Copy exact checkpoint dependencies into a private active-segment fixture."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from neraium_poly.data import EventStore
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase47.cohort import FROZEN

frozen,capsule,out=map(Path,sys.argv[1:4])
source=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
state_path=capsule/'experimental-paper/service.sqlite'
with closing(sqlite3.connect(state_path.as_uri()+'?mode=ro',uri=True)) as db:
    checkpoint,checksum=db.execute("SELECT payload,digest FROM state WHERE key='quote_archive'").fetchone()
assert hashlib.sha256(checkpoint.encode()).hexdigest()==checksum
required=set(FROZEN)|{row['full_book_id'] for row in json.loads(checkpoint).values()}
archive=ReadonlyArchive(source)
subset=ReadonlyArchive(frozen)
dest=capsule/'segment-00090000.sqlite'
assert not dest.exists() and not dest.resolve().is_relative_to(source)
fixture=EventStore(dest)
rows={}
for identity in sorted(required):
    kind,payload,checksum=archive.get(identity)
    record=json.loads(payload)
    existing=subset.get(identity)
    if existing is None:
        assert fixture._append_payload(identity,kind,record['available_at'],record['timestamp'],payload)
        assert fixture.get(identity)==(kind,payload,checksum)
    else:
        assert existing==(kind,payload,checksum)
    rows[identity]={'kind':kind,'payload_sha256':checksum,'in_existing_subset':existing is not None}
assert fixture.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()==(0,0,0)
fixture.close()
out.write_text(json.dumps({'active_segment_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
    'scope':'Exact stored quote and frozen trial bytes, imported only into test fixture. The test archive is still a subset.',
    'required_records':rows},indent=2)+'\n')
