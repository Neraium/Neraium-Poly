"""Bounded actual immutable-payload header-indexing probe, not live P/L."""
import hashlib
import json
import pathlib
import sys
import time
import tracemalloc
from datetime import datetime

from neraium_poly.data.store import _payload_metadata

payload=pathlib.Path(sys.argv[1]).read_text();original=json.loads(payload)
identity,available,event=original['id'],original['available_at'],original['timestamp']
del original


def before():
    parsed=json.loads(payload)
    assert parsed['id']==identity
    assert datetime.fromisoformat(parsed['available_at'])==datetime.fromisoformat(available)
    assert datetime.fromisoformat(parsed['timestamp'])==datetime.fromisoformat(event)
    return int(parsed['qualified']) if type(parsed.get('qualified')) is bool else -1


def after():return _payload_metadata(payload,identity,available,event)


results={}
for name,fn in [('full_header_decode',before),('metadata_only_header',after)]:
    tracemalloc.start();start=time.monotonic()
    for _ in range(30):assert fn()==-1
    elapsed=time.monotonic()-start;current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    results[name]={'elapsed_seconds':elapsed,'peak_traced_bytes':peak,'current_traced_bytes':current,'iterations':30}
print(json.dumps({'actual_payload_bytes':len(payload.encode()),'actual_payload_sha256':hashlib.sha256(payload.encode()).hexdigest(),
    'scope':'read-only actual VolumeStudy full JSON header extraction; one bounded probe, no process OOM causal claim',
    'results':results,'serialization_calls_per_managed_append':{'before':2,'after':1},'original_bytes_changed':False},indent=2))
