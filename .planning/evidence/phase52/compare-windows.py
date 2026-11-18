"""Compare the retained Phase 49 baseline with the three completed Phase 52 windows."""
import gzip
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE49 = HERE.parent / 'phase49'
samples = HERE / 'freshness-polls.jsonl.gz'
joins = HERE / 'verified-processing-frames.json'
summary = HERE / 'freshness-summary.json'

subprocess.run([sys.executable,str(PHASE49/'join-processing-frames.py'),str(samples),str(joins)],check=True,timeout=60)
subprocess.run([sys.executable,str(PHASE49/'summarize.py'),str(samples),str(summary),str(joins)],check=True,timeout=60)

now = json.loads(summary.read_bytes())['windows']
before = json.loads((PHASE49/'baseline/summary.json').read_bytes())['windows']
with gzip.open(summary.with_suffix('.traces.jsonl.gz'),'rt') as stream:
    traces = [json.loads(line) for line in stream]

results = []
for i, row in enumerate(now):
    window = [trace for trace in traces if trace['window']==i]
    failures = {
        failure['failed_at']:failure for trace in window
        if (failure:=trace.get('last_processing_failure')) and failure.get('failed_at')
    }
    current_expiry_polls = sum(
        trace['observed_boundary']=='after_valid_read_before_publication'
        or 'frame expired' in (trace.get('last_processing_failure') or {}).get('error','').lower()
        and trace['observed_boundary']=='processing_error'
        for trace in window
    )
    processing_ids = {
        stage['processing_frame_id'] for trace in window for stage in trace['producer_reads']
        if stage.get('processing_frame_id')
    }
    journal_ids = {
        trace['journal_processing_frame']['processing_frame_id'] for trace in window
        if trace.get('journal_processing_frame')
    }
    results.append({
        'window':i+1,
        'phase49_baseline':before[i],
        'observed':row,
        'distinct_processing_frame_ids':len(processing_ids | journal_ids),
        'distinct_journal_rejoined_ids':len(journal_ids),
        'distinct_receipt_processing_ids':len(processing_ids),
        'current_processing_expiry_polls':current_expiry_polls,
        'retained_distinct_worker_failures_seen':dict(Counter(
            row.get('error','unknown') for row in failures.values()
        )),
    })
output = {
    'baseline':'Phase 49 concurrent five-second API polling and existing freshness verdict',
    'cycle_percentiles':'one value per distinct report, median and nearest-rank p95',
    'frame_definition':'union of decision-receipt processing frame IDs and archive-verified StrategyCycle frame IDs',
    'classification_limit':'polls can observe the same report or failure more than once; retained failure samples do not count unseen events',
    'windows':results,
}
(HERE/'comparison.json').write_text(json.dumps(output,indent=2)+'\n')
for row in results:
    print(row['window'],row['observed']['fresh'],row['observed']['total'],row['distinct_processing_frame_ids'],row['observed']['cycle_seconds'])
