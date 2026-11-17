"""Recover journaled processing frame IDs for older samples where provenance matches."""
import gzip
import json
import sys
from pathlib import Path
from datetime import datetime

from neraium_poly.research.phase17.provenance import ReadonlyArchive

archive = ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
source = Path(sys.argv[1])
open_file = gzip.open if source.suffix == '.gz' else open
with open_file(source, 'rt') as stream:
    pairs = {(report['cycles'], report['input_frame_available_at'])
             for line in stream if (report := json.loads(line).get('research',{})).get('input_frame_available_at')}
results = {}
cache = {}
for sequence, admitted in sorted(pairs):
    match = None
    for index in range(sequence, max(0,sequence-4), -1):
        if index not in cache:
            raw = archive.get(f'strategy42:{index:012d}')
            cache[index] = json.loads(raw[1]) if raw else {}
        row = cache[index]
        observed = row.get('observations',{})
        if observed.get('frame_available_at') and datetime.fromisoformat(observed['frame_available_at']) == datetime.fromisoformat(admitted):
            match = {'cycle_id':row['id'],'processing_frame_id':observed['frame_id'],
                     'processing_frame_sha256':observed['frame_sha256'],'processing_available_at':admitted}
            break
    results[admitted] = match
Path(sys.argv[2]).write_text(json.dumps({
    'observations':results,
    'matched':sum(row is not None for row in results.values()),
    'unmatched':sum(row is None for row in results.values()),
    'limitation':'These are verified StrategyCycle processing IDs. The supplemental merge produces a derived ID; exact producer ID and source age at publication remain unavailable in legacy samples.'},indent=2)+'\n')
