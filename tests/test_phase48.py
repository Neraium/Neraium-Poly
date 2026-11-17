"""Migration controls on isolated fixtures; never operate on a live root."""
import json
import shutil
from pathlib import Path

import pytest
from neraium_poly.research.phase48.migration import Migration, allocation


def corpus(tmp_path):
    root=tmp_path/'native';source=Path('.planning/evidence/phase44/native-spx2');shutil.copytree(source,root/'v44-fixture')
    # Duplicate immutable original payload, separate provenance paths.
    p=next((root/'v44-fixture/raw').glob('*.json'));other=root/'legacy/raw/copy.json';other.parent.mkdir(parents=True);shutil.copyfile(p,other);shutil.copyfile(p,other.with_name('another-copy.json'))
    return root


def test_copy_migration_roundtrip_preserves_all_bytes_proofs_and_capacity(tmp_path):
    root=corpus(tmp_path);m=Migration(root,tmp_path/'journal');before=m.verify();result=m.migrate()
    assert result['proofs_verified']==1 and result['after']['unique_bytes']<before['unique_bytes'] and result['after']['allocated_bytes']<before['allocated_bytes']
    assert result['after']['unique_inodes']<result['after']['files']
    restored=m.restore();assert restored['unique_bytes']<=64*1024**2
    assert all((root/p).exists() for p in m.plan['files']);m.verify();m.close()
    resumed=Migration(root,tmp_path/'journal');resumed.migrate();resumed.verify();resumed.close()


@pytest.mark.parametrize('point',['linked','dedup_switched','gzip_staged','gzip_installed','raw_switched','restore_staged','restore_switched'])
def test_interrupted_migration_or_restore_resumes_without_losing_evidence(tmp_path,point):
    root=corpus(tmp_path);raised=[]
    def crash(where):
        if where==point and not raised:raised.append(where);raise RuntimeError('CONTROLLED interruption')
    m=Migration(root,tmp_path/'journal',hook=crash)
    if point.startswith('restore'):
        m.migrate()
        with pytest.raises(RuntimeError):m.restore()
    else:
        with pytest.raises(RuntimeError):m.migrate()
    m.close();assert raised
    recovered=Migration(root,tmp_path/'journal');recovered.migrate();recovered.verify();recovered.restore();recovered.verify();recovered.close()


def test_tampering_is_withheld_not_repaired_as_success(tmp_path):
    root=corpus(tmp_path);m=Migration(root,tmp_path/'journal');m.migrate();p=next((root/'v44-fixture/raw').glob('*.gz'));p.write_bytes(b'corrupt')
    with pytest.raises((ValueError,OSError,EOFError)):m.verify()
    m.close()


def test_journal_or_plan_mutation_blocks_recovery(tmp_path):
    root=corpus(tmp_path);j=tmp_path/'journal';m=Migration(root,j);m.migrate();m.close();p=j/'plan.json';v=json.loads(p.read_bytes());v['version']='altered';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='chain or plan'):Migration(root,j)


def test_allocation_counts_shared_data_once_and_refuses_symlinks(tmp_path):
    import os
    p=tmp_path/'one';p.write_bytes(b'same');os.link(p,tmp_path/'two');a=allocation(tmp_path);assert a['logical_bytes']==8 and a['unique_bytes']==4
    (tmp_path/'bad').symlink_to(p)
    with pytest.raises(ValueError):allocation(tmp_path)


def test_partial_owned_temporary_is_retained_and_recovery_is_valid(tmp_path,monkeypatch):
    from neraium_poly.research.phase48 import migration
    root=corpus(tmp_path);m=Migration(root,tmp_path/'journal');original=migration.durable;fired=[]
    def broken(path,data):
        if path.name.endswith('.48-gzip.tmp') and not fired:
            fired.append(True);path.write_bytes(data[:max(1,len(data)//2)]);raise OSError('CONTROLLED partial write')
        return original(path,data)
    monkeypatch.setattr(migration,'durable',broken)
    with pytest.raises(OSError):m.migrate()
    m.close();monkeypatch.setattr(migration,'durable',original)
    recovered=Migration(root,tmp_path/'journal');recovered.migrate();recovered.verify();assert list(root.rglob('*.partial-*'));recovered.close()


def test_exclusive_migration_lease(tmp_path):
    root=corpus(tmp_path);m=Migration(root,tmp_path/'journal')
    with pytest.raises(ValueError,match='owns'):Migration(root,tmp_path/'other-journal')
    m.close()


def test_authentic_phase47_positive_and_zero_proofs_replay_through_migration(tmp_path):
    from neraium_poly.research.phase44.native import replay
    root=corpus(tmp_path)
    for kind,y in (('positive',1),('zero',0)):
        p=root/('v44-'+kind);shutil.copytree(Path('.planning/evidence/phase48/fixtures')/kind,p);assert replay(p)['payout']==y
    m=Migration(root,tmp_path/'journal');original=m.verify();result=m.migrate();assert result['proofs_verified']==3 and result['after']['unique_bytes']<original['unique_bytes'];m.restore();m.verify();m.close()


async def test_native_source_authentication_remains_required_off_quote_tick(tmp_path,monkeypatch):
    from datetime import UTC, datetime, timedelta

    from neraium_poly.data import EventStore
    from neraium_poly.research.phase44 import outcomes
    store=EventStore(':memory:');now=datetime.now(UTC);f={'id':'CONTROLLED','market_id':'m','event_id':'e','token_id':'t','rules_sha256':'r','event_end_time':(now-timedelta(hours=1)).isoformat()};seen=[]
    # Missing original source prevents any network acquisition or result.
    def forbidden(*args,**kwargs):seen.append(True);raise AssertionError('network must remain vetoed')
    monkeypatch.setattr(outcomes,'acquire',forbidden)
    found=await outcomes.collect({'CONTROLLED':{'forecast':f,'study_id':'MISSING','study_sha256':'expected'}},store,tmp_path/'native',clock=lambda:now,can_write=lambda:True)
    assert not found and not seen
    assert 'original settlement study missing' in store.latest('NativePayout44',1)[0]['reason'];store.close()
