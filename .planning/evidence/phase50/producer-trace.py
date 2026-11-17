"""Associate producer frame health with its transport generation and gap metrics."""
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from neraium_poly.research.phase42.sources import read_reference

path = Path(__file__).with_name('producer-trace.jsonl')
with path.open('x') as out:
    for _ in range(20):
        start = time.monotonic()
        row = {'read_started_at':datetime.now(UTC).isoformat()}
        try:
            frame = read_reference('http://127.0.0.1:18742/api/market-frame')
            keys=('ws_connected','connection_generation','cached_books','fresh_books','gap_tokens_withheld',
                  'invalidations','gaps','reconnects','last_reconnect_reason','last_gap_at','last_message_at',
                  'resnapshot_pending','queue_depth','queue_overflows','backpressure_waits')
            row.update(frame_id=frame.id,source_timestamp=frame.timestamp.isoformat(),
                       available_at=frame.available_at.isoformat(),health=frame.producer_health,
                       exported_books=len(frame.books),transport={key:frame.connectivity.get(key) for key in keys})
        except (httpx.HTTPError, ValueError, OSError) as error:
            row['error']=f'{type(error).__name__}:{error}'
        row['read_ended_at']=datetime.now(UTC).isoformat()
        row['duration_seconds']=time.monotonic()-start
        out.write(json.dumps(row)+'\n')
        out.flush()
        time.sleep(max(0,5-row['duration_seconds']))
