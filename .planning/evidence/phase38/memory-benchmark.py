"""Controlled allocator fragmentation; not a live service restart or OOM proof."""
import json
from neraium_poly.data.memory_reserve import AllocatorReserve
from neraium_poly.research.phase28.memory import allocator_snapshot

def rss():
    for line in open('/proc/self/status'):
        if line.startswith('VmRSS:'): return int(line.split()[1])*1024
blocks=[bytearray(b'x'*65536) for _ in range(4096)]
anchors=blocks[::64]
del blocks
before={'rss_bytes':rss(),'allocator':allocator_snapshot()}
result=AllocatorReserve().release()
after={'rss_bytes':rss(),'allocator':allocator_snapshot()}
assert all(x[0]==120 and len(x)==65536 for x in anchors)
print(json.dumps({'kind':'controlled_fragmentation_fixture','before':before,'after':after,'release':result,'live_objects_preserved':True}))
