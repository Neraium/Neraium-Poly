"""Bounded read-only sampler diagnostics; no native/archive/risk writes."""
import json,time,hashlib
from pathlib import Path
from datetime import UTC,datetime
import httpx
from neraium_poly.research.phase42.sources import read_reference
from neraium_poly.experimental.feed import SharedFeedClient
from neraium_poly.data import assess_book
HERE=Path(__file__).resolve().parent
with httpx.Client(timeout=5,trust_env=False) as client:
 for i in range(8):
  r={'at':datetime.now(UTC).isoformat()};began=time.monotonic()
  try:r['experimental']=client.get('http://127.0.0.1:18743/api/health').json();r['reference_health']=client.get('http://127.0.0.1:18742/api/health').json()
  except httpx.HTTPError as e:r['health_error']=str(e)
  try:
   frame=read_reference('http://127.0.0.1:18742/api/market-frame');r['frame_sha256']=hashlib.sha256(frame.model_dump_json().encode()).hexdigest();r['producer_health']=frame.producer_health;SharedFeedClient.validate(frame,datetime.now(UTC));r['healthy_books']=sum(assess_book(b,datetime.now(UTC)).healthy for b in frame.books)
  except (ValueError,OSError,httpx.HTTPError) as e:r['read_error']=type(e).__name__+':'+str(e)
  r['seconds']=time.monotonic()-began
  with (HERE/'reference-diagnostic.jsonl').open('a') as out:out.write(json.dumps(r)+'\n')
  time.sleep(max(0,5-r['seconds']))
