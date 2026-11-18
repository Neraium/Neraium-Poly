"""Bound added on-disk footprint and retain runtime limit and I/O samples."""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC,datetime
from pathlib import Path

root=Path(sys.argv[1])
out=Path(sys.argv[2])
assert root.parent==Path('/home/ubuntu') and root.name.startswith('phase51-full.')
floor=108*1024**3
per_run=12*1024**3

def blocks(directory):
    total=0
    for dirname, dirs,files in os.walk(directory,followlinks=False):
        for name in files:
            try:
                total+=(Path(dirname)/name).stat(follow_symlinks=False).st_blocks*512
            except FileNotFoundError:
                pass
    return total

until=time.monotonic()+5250
with out.open('a') as stream:
    while time.monotonic()<until:
        done=True
        for name in tuple(sys.argv[3:]) or ('a1','b1','b2','a2'):
            unit=f'phase51-full-{name}.service'
            area=root/'runs'/name
            if not(area/'out/result.json').is_file():
                done=False
            cg=Path('/sys/fs/cgroup/system.slice')/unit
            if not cg.is_dir():
                continue
            row={'at':datetime.now(UTC).isoformat(),'run':name,'live_free_bytes':shutil.disk_usage(root).free,
                 'upper_allocated_bytes':blocks(area/'upper')}
            for key in ('memory.current','memory.peak','memory.events','memory.max','cpu.max','cpu.stat','io.stat','pids.max','io.pressure'):
                try:row[key]=(cg/key).read_text().strip()
                except FileNotFoundError:pass
            stream.write(json.dumps(row)+'\n')
            stream.flush()
            if row['live_free_bytes']<floor or row['upper_allocated_bytes']>per_run:
                subprocess.run(['systemctl','stop',unit],check=True,timeout=45)
                raise SystemExit('phase51 reserve watcher stopped the isolated benchmark')
        if done:
            break
        time.sleep(15)
