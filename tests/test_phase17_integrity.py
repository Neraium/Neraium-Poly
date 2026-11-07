"""Controlled integrity fixtures; none are authentic research observations."""

import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.research.phase16.continuous import ContinuousQualification
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase17.storage import GIB, retention_proposal, storage_growth
from test_phase16_continuous import frame
from test_phase16_history import START


def managed(tmp_path):
    return ManagedEventStore(tmp_path/'events.sqlite', segment_bytes=65536,
                             budget_bytes=32*1024**2, min_free_bytes=0)


def test_readonly_reader_replays_while_owner_active_without_altering_data(tmp_path):
    store = managed(tmp_path)
    try:
        for i in range(30):
            store.append(Record(id=f'CONTROLLED-{i}', timestamp=START, available_at=START, source='fixture'))
        store.maintain()
        before = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*.sqlite')}
        with ReadonlyArchive(tmp_path) as reader:
            assert reader.get('missing') is None
            assert len(reader.latest('Record',100)) == 30
            assert reader.get('CONTROLLED-0')[0] == 'Record'
            sealed = store.catalog.execute("SELECT name FROM segments WHERE status='sealed' AND gzip_sha IS NOT NULL LIMIT 1").fetchone()
            assert sealed and reader.verify_segment(sealed[0])['gzip_roundtrip_verified']
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == sha for p,sha in before.items())
        with pytest.raises(ValueError,match='closed'):
            reader.latest('Record')
    finally:
        store.close()


def test_source_missing_partial_and_changed_payload_never_read_as_verified(tmp_path):
    store = managed(tmp_path)
    row = Record(id='CONTROLLED', timestamp=START, available_at=START, source='fixture')
    store.append(row)
    source = store.catalog.execute('SELECT segment FROM records').fetchone()[0]
    store.close()
    path = tmp_path/'events-segments'/source
    with ReadonlyArchive(tmp_path) as reader:
        old = path.read_bytes();path.write_bytes(b'CONTROLLED-interrupted-database')
        with pytest.raises(sqlite3.DatabaseError):reader.get(row.id)
        path.write_bytes(old)
        assert reader.get(row.id)
        c=sqlite3.connect(path);c.execute('DROP TRIGGER events_no_update');c.execute("UPDATE events SET payload='{}'");c.commit();c.close()
        with pytest.raises(ValueError,match='integrity'):reader.get(row.id)
        path.unlink()  # Controlled disposable test fixture only.
        with pytest.raises(ValueError,match='existing'):reader.get(row.id)


def test_query_limits_symlinks_and_traversal_reject(tmp_path):
    store=managed(tmp_path);store.append(Record(id='CONTROLLED',timestamp=START,available_at=START,source='fixture'));store.close()
    with ReadonlyArchive(tmp_path) as reader:
        for n in [True,0,1001]:
            with pytest.raises(ValueError):reader.latest('Record',n)
        with pytest.raises(ValueError):reader.get('x'*513)
        with pytest.raises(ValueError):reader._source_path('../events.sqlite')
        with pytest.raises(ValueError):reader.verify_segment('segment-00000001.sqlite')
    link=tmp_path/'linked';link.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):ReadonlyArchive(link)


def test_authenticated_points_pairs_and_restart_match_native_studies(tmp_path):
    store=managed(tmp_path);study=ContinuousQualification(store);history=CausalHistory();all_studies=[];pairs=[];points=[]
    try:
        for i in range(6):
            f,at=frame(i);study.observe(f,now=at);all_studies.append(store.latest('QualificationStudy',1)[0])
            result=history.observe(f,now=at);points.extend(result['accepted']);pairs.extend(result['matured'])
        with ReadonlyArchive(tmp_path) as reader:
            for raw in all_studies:assert reader.verify_study(raw)
            p=points[0];assert reader.verify_point(p,all_studies[0])
            changed=deepcopy(p);changed['bid']+=.001;assert not reader.verify_point(changed,all_studies[0])
            pair=pairs[0];bytime={r['available_at'].replace('Z','+00:00'):r for r in all_studies}
            a=bytime[pair['decision']['observed_at']];b=bytime[pair['label']['observed_at']]
            assert reader.verify_pair(pair,a,b)
            changed=deepcopy(pair);changed['independent_outcome']=True;assert not reader.verify_pair(changed,a,b)
            changed=deepcopy(pair);changed['event_id']='other';assert not reader.verify_pair(changed,a,b)
            changed=deepcopy(a);changed['raw_frame']['books'][0]['asks'][0]['price']+=.001
            assert not reader.verify_point(p,changed)
            assert ContinuousQualification(reader)._state()==study._state()
    finally:store.close()


def test_compressed_copy_corruption_does_not_damage_original(tmp_path):
    store=managed(tmp_path)
    try:
        for i in range(30):store.append(Record(id=str(i),timestamp=START,available_at=START,source='fixture'))
        store.maintain();name=store.catalog.execute("SELECT name FROM segments WHERE gzip_sha IS NOT NULL LIMIT1".replace('LIMIT1','LIMIT 1')).fetchone()[0]
        raw=tmp_path/'events-segments'/name;sha=hashlib.sha256(raw.read_bytes()).hexdigest()
        compressed=raw.with_name(raw.name+'.gz');compressed.write_bytes(b'CONTROLLED-invalid-gzip')
        with ReadonlyArchive(tmp_path) as reader, pytest.raises(ValueError,match='compressed'):
            reader.verify_segment(name)
        assert hashlib.sha256(raw.read_bytes()).hexdigest()==sha
    finally:store.close()


def samples(delta=6000):
    return [{'at':START.isoformat(),'usage_bytes':GIB,'tier_usage_bytes':{'derived_cache':1024}},
            {'at':(START+timedelta(seconds=600)).isoformat(),'usage_bytes':GIB+delta,'tier_usage_bytes':{'derived_cache':2048}}]


def capacity(rows,**kw):
    return storage_growth(rows,now=START+timedelta(seconds=600),budget_bytes=16*GIB,
                          free_bytes=100*GIB,**kw)


def test_growth_forecast_restarts_exactly_and_never_grants_retirement():
    a=capacity(samples());b=capacity(json.loads(json.dumps(samples())))
    assert a==b and a['net_retained_growth_bytes_per_second']==10 and not a['backpressure']
    assert a['seconds_to_capacity']>0 and not a['representative24h']
    assert not a['original_removal_authorized'] and a['tier_classes']['derived_cache']['usage_bytes']==2048
    slower=capacity(samples(),additional_bytes_per_second=20)
    assert slower['seconds_to_capacity']<a['seconds_to_capacity']


def test_unknown_decreasing_stale_future_or_duplicate_storage_does_not_mean_infinite_runway():
    assert capacity([])['backpressure']
    assert capacity(samples(-5))['seconds_to_capacity'] is None
    assert capacity(samples(0))['seconds_to_capacity'] is None
    r=samples();r[1]['at']=r[0]['at'];assert capacity(r)['backpressure']
    r=samples();r[1]['at']=(START+timedelta(seconds=601)).isoformat();assert capacity(r)['backpressure']
    assert capacity(samples()[:1])['backpressure']
    with pytest.raises(ValueError):capacity(samples(),additional_bytes_per_second=float('nan'))


def test_disk_full_and_saturation_fail_closed_without_removing_data():
    r=storage_growth(samples(),now=START+timedelta(seconds=600),budget_bytes=16*GIB,free_bytes=7*GIB)
    assert r['backpressure'] and 'global_filesystem_floor' in r['alerts']
    r=capacity(samples(),proposed_bytes=16*GIB)
    assert r['backpressure'] and r['headroom_bytes']==0
    r=storage_growth(samples(),now=START+timedelta(seconds=600),budget_bytes=16*GIB,free_bytes=9*GIB,proposed_bytes=2*GIB)
    assert r['backpressure'] and 'proposed_write_crosses_filesystem_floor' in r['alerts']


def test_retention_proposal_is_not_authorization_and_unknown_capacity_rejects():
    r=retention_proposal({'usage_bytes':GIB,'budget_bytes':16*GIB,'tier_usage_bytes':{'derived_cache':1000}},verified_cold_bytes=42)
    assert r['current_policy']=='retain_original' and not r['removal_authorized'] and not r['policy_changed']
    assert len(r['original_retirement_prerequisites'])==6
    with pytest.raises(ValueError):retention_proposal({})


def test_payload_and_total_query_byte_caps_fail_before_unbounded_replay(tmp_path):
    store=managed(tmp_path)
    try:
        for i in range(3):
            store.append(Record(id=f'controlled-{i}',timestamp=START,available_at=START,source='fixture-'+('x'*1500)))
        with ReadonlyArchive(tmp_path,max_payload_bytes=1024,max_query_bytes=2048) as reader, pytest.raises(ValueError,match='oversized'):
            reader.get('controlled-0')
        with ReadonlyArchive(tmp_path,max_payload_bytes=2048,max_query_bytes=2048) as reader, pytest.raises(ValueError,match='query byte budget'):
            reader.latest('Record',3)
    finally:store.close()


def test_changed_manifest_is_detected_without_any_retirement(tmp_path):
    store=managed(tmp_path)
    try:
        for i in range(30):store.append(Record(id=str(i),timestamp=START,available_at=START,source='fixture'))
        store.maintain()
        name=store.catalog.execute("SELECT name FROM segments WHERE status='sealed' AND gzip_sha IS NOT NULL LIMIT 1").fetchone()[0]
        manifest=tmp_path/'events-segments'/(name+'.manifest.json');value=json.loads(manifest.read_text())
        value['records']+=1;manifest.write_text(json.dumps(value))
        with ReadonlyArchive(tmp_path) as reader,pytest.raises(ValueError,match='manifest/catalog'):
            reader.verify_segment(name)
        assert (tmp_path/'events-segments'/name).exists()
    finally:store.close()



def test_authenticated_chain_requires_contiguous_order_without_lost_or_duplicate_studies(tmp_path):
    store=managed(tmp_path);study=ContinuousQualification(store);rows=[]
    try:
        for i in range(5):
            f,at=frame(i);study.observe(f,now=at);rows.append(store.latest('QualificationStudy',1)[0])
        with ReadonlyArchive(tmp_path) as reader:
            assert reader.verify_chain(rows)
            assert reader.verify_chain(rows[2:])  # First boundary's external parent is permitted.
            assert reader.verify_chain(rows[:1])
            assert not reader.verify_chain([])
            assert not reader.verify_chain(list(reversed(rows)))
            assert not reader.verify_chain([rows[0],rows[2],rows[3]])
            assert not reader.verify_chain([rows[0],rows[1],rows[1],rows[2]])
            changed=deepcopy(rows);changed[2]['parent_id']=rows[0]['id']
            assert not reader.verify_chain(changed)
            changed=deepcopy(rows);changed[2]['timestamp']=rows[1]['timestamp']
            assert not reader.verify_chain(changed)
            changed=deepcopy(rows);changed[2]['available_at']=rows[1]['available_at']
            assert not reader.verify_chain(changed)
            assert not reader.verify_chain([None])
            assert not reader.verify_chain(rows*201)  # 1005 exceeds row limit before I/O.
        with ReadonlyArchive(tmp_path,max_payload_bytes=1024,max_query_bytes=2048) as small:
            assert not small.verify_chain(rows)  # Byte budget includes source frame/checkpoint.
    finally:store.close()
