"""Controlled engineering evidence; fixture contents are not market observations."""
import gzip
import hashlib

from neraium_poly.data.segmented import COMPRESSION_LEVEL, COMPRESSION_PROFILE
from test_segmented_archive import managed, record


def test_new_segment_profile_restores_exact_source_and_keeps_legacy_copies(tmp_path,monkeypatch):
    from neraium_poly.data import segmented
    monkeypatch.setattr(segmented,'COMPRESSION_LEVEL',1)
    store=managed(tmp_path/'events.sqlite')
    try:
        for i in range(20):store.append(record(i))
        store.maintain()
        row=store.catalog.execute("SELECT * FROM segments WHERE gzip_sha IS NOT NULL ORDER BY name LIMIT 1").fetchone()
        original=store._source(row['name']);compressed=original.with_suffix('.sqlite.gz')
        raw_sha=hashlib.sha256(original.read_bytes()).hexdigest();gzip_sha=hashlib.sha256(compressed.read_bytes()).hexdigest()
        assert hashlib.sha256(gzip.decompress(compressed.read_bytes())).hexdigest()==raw_sha==row['raw_sha']
        assert gzip_sha==row['gzip_sha']
        assert store.status()['future_compression_profile']==COMPRESSION_PROFILE and COMPRESSION_LEVEL==6
        prior_payloads={v['record']['id']:v['record'] for v in store.iter_replay()}
    finally:store.close()
    monkeypatch.setattr(segmented,'COMPRESSION_LEVEL',6)
    recovered=managed(tmp_path/'events.sqlite')
    try:
        recovered.maintain()
        assert hashlib.sha256(original.read_bytes()).hexdigest()==raw_sha
        assert hashlib.sha256(compressed.read_bytes()).hexdigest()==gzip_sha
        assert {v['record']['id']:v['record'] for v in recovered.iter_replay()}==prior_payloads
        assert not recovered.append(record(0))
    finally:recovered.close()


def test_competition_adapter_preserves_logical_state_and_physical_hash_restart(tmp_path):
    import json
    from datetime import timedelta

    from neraium_poly.data.store import EventStore
    from neraium_poly.research.phase14.relationships import digest
    from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
    from neraium_poly.research.phase23.operations import CompetitionStudy, ContinuousCompetition
    from neraium_poly.research.phase33.competition_storage import CompetitionStorageAdapter
    from test_phase23_competition import frame
    from test_segmented_archive import NOW

    store=EventStore(tmp_path/'controlled.sqlite');now=[NOW]
    try:
        # Original gzip1 wire is inserted before enabling future encoding.
        old=ContinuousCompetition(store,clock=lambda:now[0])
        assert old.step(frame(NOW))
        original=store.latest('CompetitionStudy',1)[0];original_source=store.get(original['id'])
        adapter=CompetitionStorageAdapter(store,clock=lambda:now[0],can_write=lambda:True)
        recovered=ContinuousCompetition(adapter,clock=lambda:now[0])
        assert recovered.state==old.state
        assert store.get(original['id'])==original_source
        now[0]+=timedelta(seconds=61);assert recovered.step(frame(now[0]))
        wire=store.latest('CompetitionStudy',1)[0];stored=store.get(wire['id']);typed=CompetitionStudy.model_validate(wire)
        assert digest(json.loads(stored[1]))==digest(typed.model_dump(mode='json'))
        assert unpack_checkpoint(wire['checkpoint'])==recovered.state
        assert wire['checkpoint_sha256']==digest(recovered.state)
        # Frozen producer bytes/code hash, history and enrollments survive.
        restarted=ContinuousCompetition(adapter,clock=lambda:now[0])
        assert restarted.state==recovered.state and restarted.code_sha==old.code_sha
        assert not restarted.step(frame(now[0]))
        assert store.count(kind='CompetitionStudy')==2
        assert not adapter.append(typed)
        assert store.get(original['id'])==original_source
        assert not adapter.append(CompetitionStudy.model_validate(original))
        assert store.get(original['id'])==original_source
        # A declared source-state mismatch cannot publish a copied checkpoint.
        bad=typed.model_copy(update={'id':'controlled-corrupt','checkpoint_sha256':'0'*64})
        import pytest
        with pytest.raises(ValueError,match='source checkpoint'):adapter.append(bad)
        assert store.get(bad.id) is None
        # The storage policy itself is append-only and idempotent on restart.
        assert CompetitionStorageAdapter(store,clock=lambda:now[0],can_write=lambda:False).policy_id==adapter.policy_id
        assert store.count(kind='CompetitionStoragePolicy')==1
        assert pack_checkpoint(unpack_checkpoint(original['checkpoint']))==original['checkpoint']
    finally:store.close()


def test_competition_policy_budget_guard_commits_no_record(tmp_path):
    import pytest
    from neraium_poly.data.store import EventStore
    from neraium_poly.research.phase33.competition_storage import CompetitionStorageAdapter
    from test_segmented_archive import NOW
    store=EventStore(tmp_path/'controlled-budget.sqlite')
    try:
        with pytest.raises(ValueError,match='archive unavailable'):
            CompetitionStorageAdapter(store,clock=lambda:NOW,can_write=lambda:False)
        assert store.count()==0
    finally:store.close()
