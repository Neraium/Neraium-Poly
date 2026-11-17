"""Capture independent account/ledger DBs and freeze exact trial JSON outside live storage."""
import hashlib
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase47.cohort import FROZEN

root=Path('/home/ubuntu/Neraium-Poly')
capsule=Path(sys.argv[1])
assert not capsule.exists() and not capsule.resolve().is_relative_to(root/'data')
capsule.mkdir()
copy_paths={}
for account in ('experimental-paper','paper-live'):
    for name in ('risk.sqlite','broker.sqlite','service.sqlite'):
        p=root/'data'/account/name
        if p.is_file():
            copy_paths[f'{account}/{name}']=p
    marker=root/'data'/account/'account.json'
    if marker.is_file():
        dest=capsule/account/marker.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(marker,dest)
for name in ('event-intelligence','event-intelligence/domains'):
    copy_paths[f'experimental-paper/{name}/forecasts.sqlite']=root/'data/experimental-paper'/name/'forecasts.sqlite'
for name,p in copy_paths.items():
    target=capsule/name
    target.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3)) as source,closing(sqlite3.connect(target)) as copy:
        source.backup(copy,pages=128,sleep=.01)
        assert copy.execute('PRAGMA integrity_check').fetchone()==('ok',)
archive=ReadonlyArchive(root/'data/experimental-paper')
originals={fid:archive.get(fid)[1] for fid in FROZEN}
(capsule/'frozen-trials.json').write_text(json.dumps(originals))
(capsule/'manifest.json').write_text(json.dumps({
    'databases':{name:hashlib.sha256((capsule/name).read_bytes()).hexdigest() for name in copy_paths},
    'frozen_trial_hashes':{fid:hashlib.sha256(raw.encode()).hexdigest() for fid,raw in originals.items()},
    'scope':'SQLite backup of committed contents, no original writes; isolated lifecycle benchmark consumes account copies. Exact frozen trials verified independently against the original archive.'},indent=2)+'\n')
