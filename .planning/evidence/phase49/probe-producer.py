"""Read-only probe outside comparative windows. One reference fetch per five seconds."""
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from neraium_poly.data import assess_book
from neraium_poly.research.phase42.sources import read_reference

here = Path(__file__).resolve().parent
with (here/'producer-probe.jsonl').open('x') as out:
    for _ in range(12):
        start = time.monotonic()
        row = {'read_started_at':datetime.now(UTC).isoformat()}
        try:
            frame = read_reference('http://127.0.0.1:18742/api/market-frame')
            quality = [assess_book(book,frame.available_at) for book in frame.books]
            row.update({
                'frame_id':frame.id,'producer_timestamp':frame.timestamp.isoformat(),
                'producer_available_at':frame.available_at.isoformat(),
                'producer_health':frame.producer_health,'books':len(quality),
                'fresh_executable_at_producer':sum(item.healthy for item in quality),
                'book_rejections':dict(Counter(reason for item in quality for reason in item.reasons)),
            })
        except (ValueError, OSError, httpx.HTTPError) as exc:
            row['error'] = f'{type(exc).__name__}:{exc}'
        row['read_finished_at'] = datetime.now(UTC).isoformat()
        row['read_seconds'] = time.monotonic()-start
        out.write(json.dumps(row)+'\n')
        out.flush()
        time.sleep(max(0,5-row['read_seconds']))
