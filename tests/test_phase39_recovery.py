"""Isolated recovery fixtures, never authentic outcomes or SII evidence."""
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase18.continuous import EventProbabilityStudy
from neraium_poly.research.phase20.continuous import ProspectiveABResearch
from neraium_poly.research.phase39.recovery import PairedRecoveryStore, recovery_sources
from test_phase20_continuous import setup
from test_segmented_archive import managed


def ignored(store,original,clock,number,padding=''):
    when=original['available_at']
    row=deepcopy(original);row.update(id=f'ignored-{number}',operation='outcome_check',
        checkpoint={'controlled_padding':padding},checkpoint_sha256='not-scientific-evidence')
    # This row has an original forecast, but the frozen experiment rejects its
    # operation before enrollment. Preserve the original stored object exactly.
    row['available_at']=when
    store.append(EventProbabilityStudy.model_validate(row))


async def test_over_64mib_ignored_context_streams_without_changing_frozen_experiment(tmp_path):
    store=EventStore(tmp_path/'fixture.sqlite')
    try:
        clock,research,original=await setup(store)
        for i in range(80):ignored(store,original,clock,i,'x'*(900*1024))
        with pytest.raises(ValueError,match='bounded paired recovery snapshot'):
            ProspectiveABResearch(store,baseline_model_sha256=None,clock=clock)
        clock.now+=timedelta(minutes=5)
        recovered=ProspectiveABResearch(PairedRecoveryStore(store,clock=clock,can_write=lambda:True),baseline_model_sha256=None,clock=clock)
        assert recovered.code_sha256==research.code_sha256
        assert recovered.experiment==research.experiment
        assert recovered.summary()['observations']==recovered.summary()['withheld']==1
        assert recovered.summary()['paired']==0
        assert recovered.summary()['rejections']=={'missed_timely_enrollment_after_recovery':1}
        audit=store.latest('PairedRecoveryAudit',1)[0]
        assert audit['result']['verified_rows']==81 and audit['result']['ignored_non_forecasts']==80
        assert audit['result']['source_bytes_verified']>64*1024**2
        assert audit['result']['retained_serialized_bytes']<64*1024**2
        assert not audit['trading_authority'] and audit['result']['scan_complete']
        assert json.loads(store.get(original['id'])[1])==original
        again=ProspectiveABResearch(PairedRecoveryStore(store,clock=clock,can_write=lambda:True),baseline_model_sha256=None,clock=clock)
        assert again.state==recovered.state
        assert store.count(kind='PairedForecastStudy')==2  # Declaration + one withholding, no duplicate.
    finally:store.close()


async def test_paged_scan_cannot_skip_beyond_the_latest_1000_raw_rows(tmp_path):
    store=EventStore(tmp_path/'fixture.sqlite')
    try:
        clock,_research,original=await setup(store)
        for i in range(1025):ignored(store,original,clock,i)
        recovered=ProspectiveABResearch(PairedRecoveryStore(store,clock=clock,can_write=lambda:True),baseline_model_sha256=None,clock=clock)
        assert recovered.summary()['observations']==1 and recovered.summary()['paired']==0
        assert store.latest('PairedRecoveryAudit',1)[0]['result']['verified_rows']==1026
    finally:store.close()


async def test_incomplete_scan_corruption_and_storage_failure_never_enroll(tmp_path):
    store=EventStore(tmp_path/'fixture.sqlite')
    try:
        clock,research,original=await setup(store)
        ignored(store,original,clock,0)
        args={'frontier':research.state['declared_at'],'cutoff':clock()}
        with pytest.raises(ValueError,match='scan incomplete'):recovery_sources(store,**args,max_rows=1)
        with pytest.raises(ValueError,match='audit storage backpressure'):
            ProspectiveABResearch(PairedRecoveryStore(store,clock=clock,can_write=lambda:False),baseline_model_sha256=None,clock=clock)
        assert store.count(kind='PairedRecoveryAudit')==0 and store.count(kind='PairedForecastStudy')==1
        store.connection.execute('DROP TRIGGER events_no_update')  # Controlled fixture only.
        store.connection.execute("UPDATE events SET digest=? WHERE id=?",('0'*64,original['id']));store.connection.commit()
        with pytest.raises(ValueError,match='hash mismatch'):recovery_sources(store,**args)
        assert store.count(kind='PairedForecastStudy')==1
    finally:store.close()


async def test_changed_checkpoint_or_policy_cannot_bypass_original_recovery_gate(tmp_path):
    store=EventStore(tmp_path/'fixture.sqlite')
    try:
        clock,_research,_original=await setup(store)
        with pytest.raises(ValueError,match='no reset'):
            ProspectiveABResearch(PairedRecoveryStore(store,clock=clock,can_write=lambda:True),baseline_model_sha256='0'*64,clock=clock)
        assert store.count(kind='PairedRecoveryAudit')==0
    finally:store.close()


async def test_managed_segments_use_existing_hash_identity_and_time_verifier(tmp_path,monkeypatch):
    store=managed(tmp_path/'events.sqlite',budget_bytes=64*1024**2)
    try:
        clock,research,original=await setup(store)
        for i in range(4):ignored(store,original,clock,i)
        sources,report=recovery_sources(store,frontier=research.state['declared_at'],cutoff=clock())
        assert sources==[original] and report['verified_rows']==5 and report['retained_originals']==1
        def corrupt(*_):raise ValueError('CONTROLLED corrupt segment')
        monkeypatch.setattr('neraium_poly.research.phase39.recovery.ReadonlyArchive._fetch',corrupt)
        with pytest.raises(ValueError,match='corrupt segment'):
            ProspectiveABResearch(PairedRecoveryStore(store,clock=clock,can_write=lambda:True),baseline_model_sha256=None,clock=clock)
        assert store.count(kind='PairedForecastStudy')==1 and store.count(kind='PairedRecoveryAudit')==0
    finally:store.close()
