"""Prepare an immutable archive inventory plus independent mutable SQLite backups."""
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
from contextlib import closing
from pathlib import Path

from neraium_poly.data import EventStore

live = Path('/home/ubuntu/Neraium-Poly/data')
source = live / 'experimental-paper'
root = Path(sys.argv[1]).resolve()
floor = 100 * 1024**3
assert root.parent == Path('/home/ubuntu') and root.name.startswith('phase51-full.')
assert not root.is_relative_to(live) and not any(root.iterdir())
seed = root/'seed'
private = seed/'experimental-paper'
segments = private/'events-segments'
segments.mkdir(parents=True)
(seed/'paper-live').mkdir()

def guard(required=0):
    if shutil.disk_usage(root).free < floor + required:
        raise RuntimeError('snapshot space would breach 100 GiB reserve')

def ro(path):
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)

def copy_db(original, clone):
    if original.is_symlink():
        raise ValueError('symlinked database')
    guard(original.stat().st_size + 512*1024**2)
    with closing(ro(original)) as src, closing(sqlite3.connect(clone)) as dst:
        # Pin a SQLite read snapshot. Copies remain independent even when the
        # producer resumes appending between separate backup calls.
        src.execute('BEGIN')
        src.execute('SELECT count(*) FROM sqlite_schema').fetchone()
        src.backup(dst)
    guard()

# The state checkpoint is captured before the archive catalog. Canonical quote
# IDs saved in that checkpoint must exist in the later published archive view.
for account in ('experimental-paper','paper-live'):
    src = live/account
    dest = seed/account
    for name in ('service.sqlite','risk.sqlite','broker.sqlite'):
        if (src/name).exists():
            copy_db(src/name,dest/name)
    if (src/'account.json').exists():
        shutil.copyfile(src/'account.json',dest/'account.json')
copy_db(source/'events-archive.sqlite',private/'events-archive.sqlite')

def hardlink_sealed(original, clone, expected_length):
    src = original.stat(follow_symlinks=False)
    if not stat.S_ISREG(src.st_mode) or src.st_size != expected_length:
        raise ValueError(f'immutable segment changed: {original.name}')
    os.link(original,clone,follow_symlinks=False)
    dst = clone.stat(follow_symlinks=False)
    assert (src.st_dev,src.st_ino,src.st_size)==(dst.st_dev,dst.st_ino,dst.st_size)

def copy_artifacts(src, dst):
    dst.mkdir(exist_ok=True)
    for entry in src.iterdir():
        if entry.is_symlink():
            raise ValueError(f'unexpected source symlink: {entry.name}')
        if entry.name.endswith(('.lock','-shm','-wal','-journal','.pending')):
            continue
        target=dst/entry.name
        if entry.is_dir():
            copy_artifacts(entry,target)
        elif entry.suffix=='.sqlite':
            copy_db(entry,target)
        else:
            guard(entry.stat().st_size)
            shutil.copyfile(entry,target)

inventory = []
with closing(ro(private/'events-archive.sqlite')) as catalog:
    catalog.row_factory=sqlite3.Row
    rows=catalog.execute('SELECT * FROM segments ORDER BY name').fetchall()
    for row in rows:
        name=row['name']
        if name == 'legacy':
            original=source/'events.sqlite'
            hardlink_sealed(original,private/'events.sqlite',row['raw_size'])
        elif row['status']=='sealed':
            original=source/'events-segments'/name
            if original.is_file():
                hardlink_sealed(original,segments/name,row['raw_size'])
            if row['gzip_sha'] is not None:
                hardlink_sealed(Path(str(original)+'.gz'),segments/(name+'.gz'),row['gzip_size'])
            for suffix in ('.manifest.json','.cold-proof.json'):
                sidecar=Path(str(original)+suffix)
                if sidecar.is_file():
                    shutil.copyfile(sidecar,segments/(name+suffix))
        elif row['status']=='active':
            # Materialize exactly the catalog-bounded committed prefix. A later
            # live append or rotation is excluded from this isolated active DB.
            original=source/'events-segments'/name
            output=EventStore(segments/name)
            included=0
            with closing(ro(original)) as active:
                active.execute('BEGIN')
                for record in catalog.execute('SELECT * FROM records WHERE segment=? ORDER BY id',(name,)):
                    stored=active.execute('SELECT kind,available_at,event_time,payload,digest FROM events WHERE id=?',(record['id'],)).fetchone()
                    assert stored is not None
                    kind,available,event,payload,digest=stored
                    assert (kind,available,event,digest)==tuple(record[k] for k in ('kind','available_at','event_time','digest'))
                    assert hashlib.sha256(payload.encode()).hexdigest()==digest
                    assert output._append_payload(record['id'],kind,available,event,payload)
                    included+=1
            output.close()
            assert included==row['records'], (included,row['records'])
        else:
            raise ValueError(f'unrecognized archive segment state: {name}')
        inventory.append(dict(row))
    epoch_records = catalog.execute('SELECT count(*) FROM records').fetchone()[0]
    assert catalog.execute('SELECT count(*) FROM segments WHERE status=\'active\'').fetchone()[0]==1
    with closing(ro(private/'service.sqlite')) as state:
        checkpoint,checksum=state.execute("SELECT payload,digest FROM state WHERE key='quote_archive'").fetchone()
        assert hashlib.sha256(checkpoint.encode()).hexdigest()==checksum
        for book in json.loads(checkpoint).values():
            assert catalog.execute("SELECT 1 FROM records WHERE id=? AND kind='OrderBookSnapshot'",(book['full_book_id'],)).fetchone()

for entry in source.iterdir():
    if entry.is_dir() and entry.name not in {'events-segments','events-cold-cache'}:
        copy_artifacts(entry,private/entry.name)
if (source/'research-projection.sqlite').is_file():
    copy_db(source/'research-projection.sqlite',private/'research-projection.sqlite')

uid=int(os.environ['SUDO_UID'])
gid=int(os.environ['SUDO_GID'])
for path in seed.rglob('*'):
    # Never chown an alias to an original sealed inode.
    if path.is_dir() or path.stat().st_nlink==1:
        os.chown(path,uid,gid)
os.chown(seed,uid,gid)
guard(24*1024**3)
statvfs=shutil.disk_usage(root)
note={'segments':len(inventory),'sealed':sum(r['status']=='sealed' for r in inventory),'records':epoch_records,
      'snapshot_free_bytes':statvfs.free,'reserve_bytes':floor,'writable_growth_stop_bytes':12*1024**3,
      'catalog_anchor':'service SQLite backup predates catalog SQLite snapshot; catalog-bounded active prefix',
      'excluded_regenerable_state':['events-cold-cache','SQLite sidecars checkpointed into copied DBs','owner locks'],
      'immutable_references':inventory}
(root/'snapshot.json').write_text(json.dumps(note,indent=2)+'\n')
print({k:v for k,v in note.items() if k!='immutable_references'},flush=True)
