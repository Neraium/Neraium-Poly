"""Measure sealed-file page residency without reading or evicting those files."""
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

seed=Path(sys.argv[1])/'seed/experimental-paper'
files=sorted(p for p in (seed/'events-segments').iterdir() if p.suffix in ('.sqlite','.gz') and p.stat().st_size)
page=os.sysconf('SC_PAGESIZE')
lib=ctypes.CDLL(None,use_errno=True)
lib.mmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_long]
lib.mmap.restype=ctypes.c_void_p
lib.mincore.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p]
lib.munmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
pages=resident=0
sample=files[::max(1,len(files)//256)]
for p in sample:
    n=p.stat().st_size
    count=(n+page-1)//page
    with p.open('rb') as f:
        mapped=lib.mmap(None,n,0,2,f.fileno(),0)
        assert mapped not in (None,ctypes.c_void_p(-1).value)
        try:
            values=(ctypes.c_ubyte*count)()
            assert lib.mincore(mapped,n,values)==0,os.strerror(ctypes.get_errno())
            resident+=sum(v&1 for v in values)
            pages+=count
        finally:
            assert lib.munmap(mapped,n)==0
print(json.dumps({'sample_files':len(sample),'resident_pages':resident,'total_pages':pages,
                  'resident_fraction':resident/pages,'page_size':page,'eviction':'none',
                  'host_meminfo':{k:v.strip() for k,v in (l.split(':',1) for l in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemAvailable','Cached','SwapTotal')},
                  'host_io_pressure':Path('/proc/pressure/io').read_text(),
                  'live_experimental_pid':subprocess.check_output(['systemctl','show','neraium-poly-experimental.service','-p','MainPID','--value'],text=True).strip()}))
