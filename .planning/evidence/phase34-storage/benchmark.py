"""Read real immutable sources; benchmark ONLY isolated new copies; no source writes."""
import gzip
import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from neraium_poly.data import segmented
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase23.operations import CompetitionStudy
from neraium_poly.research.phase33.competition_storage import CompetitionStorageAdapter

root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
c=sqlite3.connect(f'file:{root}/events-archive.sqlite?mode=ro',uri=True)
refs=c.execute("SELECT r.id,r.segment,r.digest FROM records r JOIN segments s ON s.name=r.segment WHERE r.kind='CompetitionStudy' AND s.status='sealed' ORDER BY r.available_at DESC LIMIT 3").fetchall();c.close()
records=[];sources=[]
for rid,segment,sha in refs:
 p=root/'events-segments'/segment;c=sqlite3.connect(f'file:{p}?mode=ro&immutable=1',uri=True);payload=c.execute('SELECT payload FROM events WHERE id=?',(rid,)).fetchone()[0];c.close();assert hashlib.sha256(payload.encode()).hexdigest()==sha
 records.append(CompetitionStudy.model_validate_json(payload));sources.append({'id':rid,'segment':segment,'payload_sha256':sha,'payload_bytes':len(payload.encode())})
results={}
with TemporaryDirectory(prefix='phase34-isolated-matched-') as tmp:
 for name,level in [('before',1),('after',6)]:
  segmented.COMPRESSION_LEVEL=level;base=Path(tmp)/name;clock=lambda:datetime.now(UTC);t=time.process_time();store=ManagedEventStore(base/'events.sqlite',segment_bytes=2*1024**2,budget_bytes=64*1024**2,min_free_bytes=0,clock=clock)
  adapter=CompetitionStorageAdapter(store,clock=clock,can_write=lambda:True) if name=='after' else store
  for record in records:adapter.append(record)
  store._seal_active();store._create_active()
  for _ in range(4):store.maintain()
  compressed=store.catalog.execute("SELECT name,raw_sha,gzip_sha FROM segments WHERE status='sealed'").fetchall()
  for row in compressed:
   raw=base/'events-segments'/row['name'];gz=Path(str(raw)+'.gz')
   assert hashlib.sha256(raw.read_bytes()).hexdigest()==row['raw_sha'];assert hashlib.sha256(gzip.decompress(gz.read_bytes())).hexdigest()==row['raw_sha'];assert hashlib.sha256(gz.read_bytes()).hexdigest()==row['gzip_sha']
  for record in records:
   physical=CompetitionStudy.model_validate_json(store.get(record.id)[1]);assert unpack_checkpoint(physical.checkpoint)==unpack_checkpoint(record.checkpoint)
   assert physical.model_copy(update={'checkpoint':record.checkpoint})==record
  preclose={str(p.relative_to(base)):p.stat().st_size for p in base.rglob('*') if p.is_file()}
  store.close();sizes={str(p.relative_to(base)):p.stat().st_size for p in base.rglob('*') if p.is_file()}
  results[name]={'retained_total_bytes':sum(sizes.values()),'active_total_including_wal_bytes':sum(preclose.values()),'files':sizes,'wal_bytes_before_close':sum(n for p,n in preclose.items() if p.endswith('-wal')),'cpu_seconds':time.process_time()-t,'restored_segments':len(compressed)}
results['sources']=sources;results['retained_reduction_fraction']=1-results['after']['retained_total_bytes']/results['before']['retained_total_bytes'];results['scope']='three genuine immutable CompetitionStudy records, isolated copies including catalog, indexes, active DB, manifest and gzip; no production source changed';Path('.planning/evidence/phase34-storage/matched-benchmark.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps({k:v for k,v in results.items() if k not in ('sources',)},indent=2))
