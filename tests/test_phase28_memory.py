"""Controlled process telemetry fixtures; never production heap interventions."""
import gc
import json

import pytest
from neraium_poly.research.phase28.memory import MemorySampler, allocator_snapshot


def proc(tmp_path, *, rss=100):
    tmp_path.joinpath('status').write_text(f'VmRSS:\t{rss} kB\nVmHWM:\t150 kB\nRssAnon:\t80 kB\nRssFile:\t20 kB\nThreads:\t5\n')
    fields=['S']+['0']*30
    for index,value in [(7,12),(9,3),(11,20),(12,30)]:fields[index]=str(value)
    tmp_path.joinpath('stat').write_text('1 (name with ) spaces) '+' '.join(fields))


def test_samples_are_bounded_throttled_and_deltas_are_since_accepted_sample(tmp_path):
    proc(tmp_path);clock=[0.]
    s=MemorySampler(proc_root=tmp_path,clock=lambda:clock[0],allocator_reader=lambda:{'status':'unavailable'})
    first=s.sample('start');assert first['rss_bytes']==100*1024 and first['minor_page_faults']==12
    assert first['major_page_faults']==3 and first['user_cpu_ticks']==20
    clock[0]=4.999;assert s.sample('end')['status']=='throttled'
    assert len(s.history)==1
    clock[0]=5.;proc(tmp_path,rss=110)
    row=s.sample('next');assert row['rss_delta_bytes']==10*1024
    assert row['interval_since_previous_seconds']==5
    assert row['peak_observed_rss_bytes']==110*1024
    for i in range(40):clock[0]+=5;s.sample('bounded')
    assert len(s.history)==32 and s.status()['maximum_samples_retained']==32
    json.dumps(s.status(),allow_nan=False)


def test_missing_or_malformed_proc_files_are_nonfatal_and_do_not_claim_rss(tmp_path):
    s=MemorySampler(proc_root=tmp_path,allocator_reader=lambda:None)
    row=s.sample('unavailable')
    assert row['status']=='partial' and row['rss_bytes'] is None
    assert 'proc_status_unavailable' in row['errors'] and row['allocator']['status']=='unavailable'
    tmp_path.joinpath('status').write_text('VmRSS: garbage kB\nVmHWM: 50 unsupported\n')
    tmp_path.joinpath('stat').write_text('malformed')
    s=MemorySampler(proc_root=tmp_path,allocator_reader=lambda:{'status':'unavailable'})
    row=s.sample('malformed');assert row['rss_bytes'] is None and row['vm_hwm_bytes'] is None


def test_no_garbage_collection_or_allocator_intervention(tmp_path,monkeypatch):
    proc(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('heap intervention forbidden')
    monkeypatch.setattr(gc,'collect',forbidden)
    s=MemorySampler(proc_root=tmp_path,allocator_reader=lambda:{'status':'available','arena':100,'uordblks':60,'fordblks':40,'unbounded_payload':[0]*100})
    row=s.sample('safe\x1b\n')
    assert row['allocator']['uordblks']==60 and 'unbounded_payload' not in row['allocator']
    assert '\n' not in row['stage'] and '\x1b' not in row['stage']
    assert s.status()['heap_interventions'] is False


def test_clock_regression_and_failure_do_not_overwrite_prior_observation(tmp_path):
    proc(tmp_path);clock=[10.]
    s=MemorySampler(proc_root=tmp_path,clock=lambda:clock[0],allocator_reader=lambda:{'status':'unavailable'})
    s.sample('first');clock[0]=9
    assert s.sample('earlier')['reason']=='memory_clock_regression'
    clock[0]=float('nan');assert s.sample('invalid')['status']=='unavailable'
    assert len(s.history)==1


@pytest.mark.parametrize('options',[{'capacity':33},{'capacity':0},{'capacity':True},{'interval_seconds':4.9},{'interval_seconds':float('inf')},{'interval_seconds':True}])
def test_unbounded_or_excessively_frequent_sampling_is_rejected(options):
    with pytest.raises(ValueError):MemorySampler(**options)


def test_oversized_proc_report_fails_closed(tmp_path):
    tmp_path.joinpath('status').write_text('A'*17000)
    s=MemorySampler(proc_root=tmp_path,allocator_reader=lambda:{'status':'unavailable'})
    assert s.sample('too_large')['rss_bytes'] is None


def test_allocator_counters_are_best_effort_readonly_and_json_serializable():
    snapshot=allocator_snapshot()
    assert snapshot['status'] in ('available','unavailable')
    if snapshot['status']=='available':
        assert all(type(snapshot[k]) is int and snapshot[k]>=0 for k in ['arena','uordblks','fordblks','hblkhd'])
    json.dumps(snapshot,allow_nan=False)


def test_missing_rss_field_is_not_reported_as_success(tmp_path):
    proc(tmp_path)
    tmp_path.joinpath('status').write_text('Name: controlled\n')
    s=MemorySampler(proc_root=tmp_path,allocator_reader=lambda:{'status':'unavailable'})
    row=s.sample('missing');assert row['status']=='partial'
    assert row['rss_bytes'] is None and 'proc_rss_counter_missing' in row['errors']


def test_unsupported_interpreter_counters_do_not_break_process_observation(tmp_path,monkeypatch):
    import sys
    proc(tmp_path)
    def unavailable():raise RuntimeError('CONTROLLED unsupported diagnostic')
    monkeypatch.setattr(sys,'getallocatedblocks',unavailable)
    monkeypatch.setattr(gc,'get_stats',unavailable)
    row=MemorySampler(proc_root=tmp_path,allocator_reader=lambda:{'status':'unavailable'}).sample('partial')
    assert row['rss_bytes']==100*1024 and row['allocated_blocks'] is None and row['gc_stats']==[]
    assert row['status']=='partial'
