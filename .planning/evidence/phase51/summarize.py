"""Summarize the four ordered runs with uncensored readiness and stage metrics."""
import json
from collections import defaultdict
from pathlib import Path

here=Path(__file__).resolve().parent
names=('a1r','b1r','b2r','a2r')
baseline=json.loads((here/'frozen-state.json').read_bytes())
resources=defaultdict(list)
for line in (here/'canonical-resource-samples.jsonl').read_text().splitlines():
    row=json.loads(line)
    resources[row['run']].append(row)
results={}
for name in names:
    path=here/'runs'/f'{name}-result.json'
    if not path.is_file():
        results[name]={'status':'missing result'}
        continue
    observed=json.loads(path.read_bytes())
    post=json.loads((here/'runs'/f'{name}-post.json').read_bytes())
    cache=json.loads((here/'runs'/f'{name}-cache.json').read_bytes())
    assert observed['state_equivalent_at_start']==baseline and post['accounts_unchanged']
    samples=resources[name]
    for row in samples:
        if row.get('memory.max'):
            assert row['memory.max']=='2147483648'
        if row.get('cpu.max'):
            assert row['cpu.max']=='100000 100000'
        if row.get('pids.max'):
            assert row['pids.max']=='32'
    stage=observed['stage_metrics_inclusive']
    metrics={
        'archive_constructor_seconds':stage['ManagedEventStore.__init__']['seconds'],
        'archive_recover_seconds':stage['ManagedEventStore._recover']['seconds'],
        'index_replay_segments':stage['ManagedEventStore._index_segment']['calls'],
        'index_replay_seconds':stage['ManagedEventStore._index_segment']['seconds'],
        'catalog_record_calls_through_readiness':stage.get('ManagedEventStore._catalog_record',{}).get('calls',0),
        'compressed_verification_seconds':stage['ManagedEventStore._verify_compressed']['seconds'],
        'standalone_hash_seconds':stage['neraium_poly.data.segmented._sha']['seconds'],
        'standalone_hash_bytes':stage['neraium_poly.data.segmented._sha']['bytes'],
        'archive_tree_measure_calls':stage['neraium_poly.data.segmented._tree_size']['calls'],
        'archive_tree_measure_seconds':stage['neraium_poly.data.segmented._tree_size']['seconds'],
        'sqlite_quick_check_seconds':stage['sqlite.quick_check']['seconds'],
    }
    results[name]={**{k:v for k,v in observed.items() if k not in ('state_equivalent_at_start','stage_metrics_inclusive','poll_rejections')},
        'state_equivalent_at_start':True,'forecast_heads_unchanged_after_ready_cycle':post['forecast_heads_equal_at_gate'],
        'cache_preflight':cache,'timings_inclusive_not_additive':metrics,
        'peak_observed_upper_allocated_bytes':max((r['upper_allocated_bytes'] for r in samples),default=None),
        'min_observed_live_free_bytes':min((r['live_free_bytes'] for r in samples),default=None),
        'max_observed_memory_peak_bytes':max((int(r['memory.peak']) for r in samples if 'memory.peak' in r),default=None),
        'oom_killed':any(int(dict(l.split() for l in r['memory.events'].splitlines()).get('oom_kill',0))
                         for r in samples if 'memory.events' in r)}
chosen=[results[name] for name in ('b1r','b2r')]
valid=[row['readiness_seconds'] for row in chosen if row.get('readiness_seconds') is not None]
completed=len(valid)==2
summary={'order':list(names),'runs':results,'candidate_readiness_repeated_pass':completed and max(valid)<=900,
         'candidate_slowest_measured_seconds':max(valid,default=None),
         'candidate_slowest_margin_seconds':900-max(valid) if completed else None,
         'resources':'1 CPU, 2 GiB RAM, 32 tasks, no host swap. Shared read-only sealed sources, private mutable DBs and ext4 overlay upper, per-run isolated mount/PID namespace. No cache evictions.',
         'frozen_trials':len(baseline['trials']),'proof_hashes':len(baseline['native']['proofs']),
         'source_files':baseline['native']['original_files']}
(here/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
for name,row in results.items():
    print(name,row.get('readiness_seconds'),row.get('margin_seconds'))
