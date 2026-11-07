"""Controlled storage fixtures; no fixture is authentic historical evidence."""

import hashlib
import json
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.cold import verify_cold_segment
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.research.phase18 import retention
from neraium_poly.research.phase18.retention import proposed_policy, retention_plan
from neraium_poly.research.phase18.storage import GIB, budget_capacity, measure_service_tree
from test_phase16_history import START


def budget(tmp_path, **changes):
    a,b=tmp_path/'collector',tmp_path/'experimental';a.mkdir(exist_ok=True);b.mkdir(exist_ok=True)
    values={'service_roots':{'collector':{'path':a,'current_usage_bytes':10*GIB},
        'experimental':{'path':b,'current_usage_bytes':3*GIB}},
        'target_budgets':{'collector':200*GIB,'experimental':100*GIB},
        'filesystem_free_bytes':470*GIB,'filesystem_capacity_bytes':967*GIB,
        'reserve_bytes':100*GIB,'temporary_headroom_bytes':4*GIB,'shared_growth_reserve_bytes':64*GIB}
    values.update(changes);return budget_capacity(**values)


def test_budget_counts_only_incremental_growth_and_preserves_all_headrooms(tmp_path):
    result=budget(tmp_path)
    assert result['approved'] and result['incremental_maximum_service_growth_bytes']==287*GIB
    assert result['projected_free_at_service_caps_bytes']==183*GIB
    assert result['projected_free_after_all_headrooms_bytes']==115*GIB
    assert not result['preallocation_performed'] and not result['configuration_changed']
    assert result['protected_free_reserve_bytes']==100*GIB


def test_capacity_floor_shortfall_or_stricter_existing_floor_cannot_pass(tmp_path):
    assert not budget(tmp_path,filesystem_free_bytes=454*GIB)['approved']
    r=budget(tmp_path,reserve_bytes=120*GIB);assert not r['approved']
    r=budget(tmp_path,reserve_bytes=8*GIB);assert r['protected_free_reserve_bytes']==100*GIB
    with pytest.raises(ValueError):budget(tmp_path,filesystem_free_bytes=True)


def test_overlapping_nested_symlink_and_other_filesystem_roots_reject(tmp_path):
    a=tmp_path/'parent';a.mkdir();b=a/'nested';b.mkdir()
    args={'service_roots':{'collector':{'path':a,'current_usage_bytes':0},'experimental':{'path':b,'current_usage_bytes':0}}}
    assert not budget(tmp_path,**args)['approved']
    link=tmp_path/'alias';link.symlink_to(a,target_is_directory=True)
    args['service_roots']['experimental']['path']=link
    with pytest.raises(ValueError,match='non-symlink'):budget(tmp_path,**args)
    args['service_roots']['experimental']={'path':b,'current_usage_bytes':0,'filesystem_device':-1}
    with pytest.raises(ValueError,match='identity'):budget(tmp_path,**args)


def test_tree_accounting_includes_temporary_manifests_hidden_and_hardlinks(tmp_path):
    (tmp_path/'active.sqlite-wal').write_bytes(b'a'*11)
    nested=tmp_path/'segments';nested.mkdir();p=nested/'source.sqlite.gz.partial';p.write_bytes(b'b'*23)
    (nested/'.manifest.pending').write_bytes(b'c'*5);os.link(p,nested/'same-inode-cache')
    r=measure_service_tree(tmp_path);assert r['current_usage_bytes']==11+23+5+23
    assert r['hardlink_pathnames_charged_conservatively']
    with pytest.raises(ValueError,match='entry budget'):measure_service_tree(tmp_path,max_entries=2)
    (tmp_path/'unsafe').symlink_to(p)
    with pytest.raises(ValueError,match='symlink'):measure_service_tree(tmp_path)


def archive(tmp_path):
    store=ManagedEventStore(tmp_path/'events.sqlite',segment_bytes=65536,budget_bytes=64*1024**2,min_free_bytes=0)
    for i in range(70):store.append(Record(id=f'CONTROLLED-{i}',timestamp=START,available_at=START,source='fixture-'+'x'*1024))
    store.maintain()
    rows=[dict(r) for r in store.catalog.execute("SELECT * FROM segments WHERE status='sealed' AND gzip_sha IS NOT NULL ORDER BY name")]
    assert rows
    for row in rows:
        raw=tmp_path/'events-segments'/row['name']
        verify_cold_segment(raw,catalog_row=row,cache_directory=tmp_path/'events-cold-cache',min_free_bytes=0,max_cache_bytes=64*1024**2)
    store.close()
    for row in rows:
        raw=tmp_path/'events-segments'/row['name']
        for suffix in ['', '.gz','.manifest.json','.cold-proof.json']:
            os.utime(str(raw)+suffix,(START.timestamp(),START.timestamp()))
    return rows


def complete_scan(_paths):return {'complete':True,'references':[],'scope':'CONTROLLED test process-reference result'}


def test_dry_run_is_not_deletion_authorization_even_when_old_sources_exist(tmp_path):
    archive(tmp_path)
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='dry_run')
    assert r['review_ready_segments']==0 and not r['removal_authorized']
    assert any('independent_audit_required_before_review' in s['reasons'] for s in r['segments'])
    assert not r['original_removal_implemented']
    assert all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in before.items())


def test_audit_binds_exact_sources_restoration_completeness_and_owner_policy(tmp_path,monkeypatch):
    archive(tmp_path);monkeypatch.setattr(retention,'process_references',complete_scan)
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit')
    assert r['review_ready_segments']>0 and r['verification_bytes']>0
    ready=[x for x in r['segments'] if x['review_prerequisites_met']]
    assert all(x['restore_verified'] and x['cold_proof_sha256'] and x['manifest_sha256'] for x in ready)
    assert all(Path(x['raw_path']).is_file() for x in ready)
    assert not r['removal_authorized'] and r['owner_approval_required']
    changed=deepcopy(r);changed.pop('proposal_sha256');assert retention._digest(changed)==r['proposal_sha256']
    p=proposed_policy();p['irreversible_actions_enabled']=True
    with pytest.raises(ValueError,match='non-destructive'):retention_plan(tmp_path,now=START,policy=p)
    with pytest.raises(ValueError,match='non-destructive'):retention_plan(tmp_path,now=START,mode='delete')


def test_process_references_and_incomplete_namespaces_prevent_review_ready(tmp_path,monkeypatch):
    rows=archive(tmp_path);raw=str(tmp_path/'events-segments'/rows[0]['name'])
    monkeypatch.setattr(retention,'process_references',lambda _:{'complete':True,'references':[{'path':raw,'pid':123}]})
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit')
    assert 'original_referenced_by_active_process' in next(x for x in r['segments'] if x['segment']==rows[0]['name'])['reasons']
    monkeypatch.setattr(retention,'process_references',lambda _:{'complete':False,'references':[]})
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit');assert r['review_ready_segments']==0


def test_partial_compression_bad_restore_proof_and_open_wal_fail_closed(tmp_path,monkeypatch):
    rows=archive(tmp_path);raw=tmp_path/'events-segments'/rows[0]['name'];original=raw.read_bytes()
    monkeypatch.setattr(retention,'process_references',complete_scan)
    gz=Path(str(raw)+'.gz');gz.write_bytes(b'CONTROLLED partial compression')
    # Keep the corrupted fixture old enough to exercise integrity, independent of host clock.
    os.utime(gz, (START.timestamp(), START.timestamp()))
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit')
    bad=next(x for x in r['segments'] if x['segment']==raw.name);assert not bad['review_prerequisites_met']
    assert any('audit_withheld:' in x for x in bad['reasons']) and raw.read_bytes()==original
    wal=Path(str(raw)+'-wal');wal.write_bytes(b'CONTROLLED open WAL')
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit')
    assert any('open_or_uncheckpointed' in reason for x in r['segments'] if x['segment']==raw.name for reason in x['reasons'])


def test_retention_warm_interval_and_audit_byte_budget_preserve_sources(tmp_path,monkeypatch):
    archive(tmp_path);monkeypatch.setattr(retention,'process_references',complete_scan)
    r=retention_plan(tmp_path,now=START+timedelta(hours=1),mode='audit');assert r['independently_verified_segments']==0
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit',max_verification_bytes=4096)
    assert r['review_ready_segments']==0 and r['verification_bytes']==0
    assert any('bounded_independent_verification_budget_reached' in x['reasons'] for x in r['segments'])
    assert not r['existing_retention_policy_changed']


def test_stale_manifest_and_record_completeness_proof_cannot_qualify(tmp_path,monkeypatch):
    rows=archive(tmp_path);raw=tmp_path/'events-segments'/rows[0]['name'];proof=Path(str(raw)+'.cold-proof.json')
    v=json.loads(proof.read_text());v['catalog_records_sha256']='0'*64;proof.write_text(json.dumps(v));os.utime(proof,(START.timestamp(),START.timestamp()))
    monkeypatch.setattr(retention,'process_references',complete_scan)
    r=retention_plan(tmp_path,now=START+timedelta(days=2),mode='audit')
    entry=next(x for x in r['segments'] if x['segment']==raw.name)
    assert not entry['review_prerequisites_met'] and any('completeness' in x for x in entry['reasons'])


def test_bounded_inventory_can_page_without_claiming_full_coverage(tmp_path):
    archive(tmp_path)
    first=retention_plan(tmp_path,now=START+timedelta(days=2),max_segments=1)
    assert first['inventory_truncated'] and first['next_cursor']
    second=retention_plan(tmp_path,now=START+timedelta(days=2),max_segments=1,after_segment=first['next_cursor'])
    assert first['segments'][0]['segment']!=second['segments'][0]['segment']
    with pytest.raises(ValueError,match='cursor'):
        retention_plan(tmp_path,now=START,after_segment='../unsafe')
