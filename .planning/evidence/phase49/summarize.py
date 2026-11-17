"""Summarize every poll and trace the first observable freshness boundary."""
import gzip
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def seconds(later, earlier):
    return (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds()


def stats(values):
    values = sorted(values)
    if not values:
        return None
    return {'p50':statistics.median(values), 'p95':values[math.ceil(.95*len(values))-1], 'max':max(values)}


def trace(row):
    report = row.get('research', {})
    evidence = report.get('freshness_trace', {})
    sample = report.get('freshness_sample', {})
    reads = evidence.get('decision_reads', [])
    reference = sample.get('reference') or row.get('health', {}).get('research_reference', {})
    sampled_at = sample.get('sampled_at') or row.get('sampled_at') or row.get('at')
    published_at = evidence.get('published_at')
    stages = []
    for receipt in reads:
        stage = {**receipt}
        source_at = receipt['source_available_at']
        stage['age_at_read_seconds'] = seconds(receipt['read_completed_at'], source_at)
        stage['age_at_decision_seconds'] = seconds(receipt['decision_at'], source_at)
        stage['age_at_publication_seconds'] = seconds(published_at, source_at)
        stage['age_at_sample_seconds'] = seconds(sampled_at, source_at)
        stages.append(stage)
    failure = reference.get('last_failure') or {}
    status = report.get('status', 'poll_error' if row.get('api_error') else 'unavailable')
    if status == 'fresh':
        boundary = 'fresh_at_sample'
    elif row.get('api_error'):
        boundary = 'dashboard_poll_failed'
    elif reference.get('status') == 'withheld' or 'reference observation' in (report.get('runtime_error') or ''):
        reason = reference.get('last_error') or failure.get('reason') or ''
        if 'Timeout' in reason:
            boundary = 'reference_timeout'
        elif 'producer is degraded' in reason:
            boundary = 'producer_degraded'
        elif 'stale or future' in reason:
            boundary = 'producer_timestamp_rejected'
        elif 'no fresh executable' in reason:
            boundary = 'producer_books_rejected'
        else:
            boundary = 'reference_withheld_cause_unknown'
    elif any(s['age_at_publication_seconds'] > 20 for s in stages):
        boundary = 'after_valid_read_before_publication'
    elif any(s['age_at_sample_seconds'] > 20 for s in stages):
        boundary = 'after_publication_before_sample'
    elif report.get('runtime_error'):
        boundary = 'processing_error'
    else:
        boundary = 'expired_source_or_report_boundary_unknown'
    input_at = report.get('input_frame_available_at')
    as_of = report.get('as_of')
    legacy_age = max(seconds(sampled_at, as_of), seconds(sampled_at, input_at)) if as_of and input_at else None
    matched_fresh = status == 'fresh' if not evidence else (
        legacy_age is not None and 0 <= legacy_age <= 20 and not report.get('runtime_error')
    )
    return {'phase48_rule_fresh':matched_fresh,'legacy_rule_age_seconds':legacy_age,'window':row.get('window'),'at':sampled_at,'status':status,'observed_boundary':boundary,
            'as_of':report.get('as_of'),'published_at':published_at,'research_age':report.get('age_seconds'),
            'cycle_seconds':report.get('shadow_worker',{}).get('cycle_seconds'),
            'processing_frame_available_at':report.get('input_frame_available_at'),
            'exploratory_frame_available_at':report.get('exploratory_frame_available_at'),
            'stage_seconds':report.get('processing_stages_seconds'),
            'reference_available_at_sample':reference.get('available_at'),
            'reference_failure':failure or None,'reference_attempts':reference.get('attempts'),
            'reference_failures':reference.get('failures'),
            'producer_reads':stages,'initial_read':evidence.get('initial_read'),
            'last_processing_failure':sample.get('last_processing_failure'),
            'api_error':row.get('api_error'),'ingestion':row.get('health',{}).get('status')}


def window(rows):
    unique = {r['published_at'] or r['as_of']: r for r in rows if r['as_of']}
    joined = {r['processing_frame_available_at'] for r in unique.values() if joins.get(r['processing_frame_available_at'])}
    ids = {s['frame_id'] for r in unique.values() for s in r['producer_reads']}
    receipts = {r['reference_available_at_sample'] for r in rows if r['reference_available_at_sample']}
    return {'fresh':sum(r['status']=='fresh' for r in rows),'total':len(rows),
            'fresh_under_phase48_age_rule':sum(r['phase48_rule_fresh'] for r in rows),
            'distinct_reports':len(unique),'repeat_report_polls':sum(bool(r['as_of']) for r in rows)-len(unique),
            'distinct_decision_source_frames':len(ids) if ids else None,
            'distinct_journal_matched_processing_frames':len(joined) if joins else None,
            'distinct_reference_availability_timestamps_at_sampling':len(receipts),
            'ingestion_healthy':sum(r['ingestion']=='ok' for r in rows),
            'api_errors':sum(bool(r['api_error']) for r in rows),
            'observed_boundaries':dict(Counter(r['observed_boundary'] for r in rows)),
            'source_age_at_publication_seconds':stats([max(s['age_at_publication_seconds'] for s in r['producer_reads'])
                                                       for r in unique.values() if r['producer_reads']]),
            'cycle_seconds':stats([r['cycle_seconds'] for r in unique.values() if r['cycle_seconds'] is not None]),
            'processing_stages':{k:stats([r['stage_seconds'][k] for r in unique.values()
                                         if k in (r['stage_seconds'] or {})])
                                 for k in ('source_inventory_replay_enrollment','legacy_and_profile_processing',
                                           'active_candidate_evaluation','settlement_application_scoring_report','decision_cards')}}


path = Path(sys.argv[1])
read_file = gzip.open if path.suffix=='.gz' else open
with read_file(path,'rt') as stream:
    rows = [trace(json.loads(line)) for line in stream]
output = Path(sys.argv[2])
joins = json.loads(Path(sys.argv[3]).read_text())['observations'] if len(sys.argv)>3 else {}
for row in rows:
    row['journal_processing_frame'] = joins.get(row['processing_frame_available_at'])
summary = {'windows':[window([r for r in rows if r['window']==i]) for i in range(3)],
           'startup_or_unpartitioned':window([r for r in rows if r['window'] is None]),
           'limitations':'Legacy reports expose reference availability and processing timestamps but lack exact original decision frame IDs and publication time. Sample classifications are observable vetoes. The post candidate also checks the original producer age at the same threshold, so the Phase 48 rule is recomputed separately using its legacy as_of and processing-frame timestamps.'}
output.write_text(json.dumps(summary,indent=2)+'\n')
with gzip.open(output.with_suffix('.traces.jsonl.gz'),'wt') as stream:
    for row in rows:
        stream.write(json.dumps(row)+'\n')
