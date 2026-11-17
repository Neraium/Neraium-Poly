"""Measure the production ManagedEventStore startup stages on an isolated archive."""
import json
import os
import resource
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from neraium_poly.data import segmented
from neraium_poly.data import cold

snapshot, work, out = map(Path, sys.argv[1:4])
assert not work.exists() and not work.resolve().is_relative_to(Path('/home/ubuntu/Neraium-Poly/data'))
shutil.copytree(snapshot, work)
metrics = defaultdict(lambda:{'calls':0,'seconds':0.,'input_bytes':0})
def wrap(target,name,nbytes=None):
    original=getattr(target,name)
    def timed(*args,**kwargs):
        stage=f'{getattr(target,"__name__",type(target).__name__)}.{name}'
        row=metrics[stage]
        row['calls']+=1
        if nbytes:
            row['input_bytes']+=nbytes(*args,**kwargs)
        start=time.perf_counter()
        try:
            return original(*args,**kwargs)
        finally:
            row['seconds']+=time.perf_counter()-start
    setattr(target,name,timed)
for name in ('_recover','_index_segment','_verify_cold','_verify_compressed','status'):
    wrap(segmented.ManagedEventStore,name)
wrap(segmented,'_tree_size')
wrap(segmented,'_sha',lambda path:path.stat().st_size)
wrap(cold,'_sha',lambda path:path.stat().st_size)
# Flush only this private copy, then advise eviction on its file inodes.
for file in work.rglob('*'):
    if file.is_file():
        with file.open('r+b') as stream:
            os.fsync(stream.fileno())
            os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_DONTNEED)

def read_io():
    return {k:int(v) for k,v in (line.split(':',1) for line in Path('/proc/self/io').read_text().splitlines())}
io_before=read_io()
start=time.perf_counter()
store=segmented.ManagedEventStore(work/'events.sqlite',segment_bytes=32*1024**2,budget_bytes=150*1024**3,min_free_bytes=100*1024**3,cold_verification_enabled=True)
ready=time.perf_counter()-start
io_after=read_io()
fingerprints={}
import hashlib
for table in ('records','segments'):
    digest=hashlib.sha256()
    for row in store.catalog.execute(f'SELECT * FROM {table} ORDER BY 1'):
        digest.update((json.dumps(tuple(row))+'\n').encode())
    fingerprints[table]=digest.hexdigest()
assert store.catalog.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
store.close()
result={'managed_archive_ready_seconds':ready,'stages_inclusive':metrics,'io':{k:v-io_before[k] for k,v in io_after.items()},'peak_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'catalog_fingerprints':fingerprints,'cache':'fsync and POSIX_FADV_DONTNEED on separate copied inodes before timer. Kernel metadata and host device caches were not globally flushed.',
        'scope':'Real selected sealed segments through production ManagedEventStore. No HTTP or account recovery timing.', 'sqlite':sqlite3.sqlite_version}
out.write_text(json.dumps(result,indent=2)+'\n')
print(ready,flush=True)
