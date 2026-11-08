"""Controlled finding-publication engineering fixtures; no authentic performance."""
from datetime import timedelta

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase27.continuous import EconomicFindingStudy, FindingsResearch
from test_phase24_integration import NOW


class InputStudy(Record):
    forecasts: list


class Index:
    def __init__(self, study):
        f=study['forecasts'][0]
        self.entries=[{'type':'forecast','replay_verified':True,'forecast_id':f['id'],'forecast_sha256':digest(f),'source_id':study['id'],'source_study_sha256':digest(study)}]
        self.anchor={'id':'CONTROLLED-anchor','available_at':NOW.isoformat()}
        self.caught_up=True
    def snapshot(self):return self.entries,self.anchor
    def report(self,**kwargs):return {'projection':{'status':'caught_up' if self.caught_up else 'bootstrapping'}}


def setup(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite')
    s=InputStudy(id='CONTROLLED-study',timestamp=NOW,available_at=NOW,source='CONTROLLED-fixture',forecasts=[{'id':'CONTROLLED-forecast','probability':.5}])
    store.append(s);return store,Index(s.model_dump(mode='json'))


def builder(studies,frame,**kwargs):
    assert kwargs['verified_forecast_ids']=={'CONTROLLED-forecast'}
    return {'findings':[{'id':'CONTROLLED-finding','net_edge':None}], 'counts':{'qualified':0},'rejections':{'calibration_unavailable':1},'research_only':True,'trading_authority':False}


def test_append_only_publication_recovers_once_per_minute_and_preserves_original(tmp_path):
    store,index=setup(tmp_path);old=store.get('CONTROLLED-study')
    try:
        c=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=builder)
        assert c.step({}) and not c.step({})
        recovered=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=builder)
        assert not recovered.step({}) and store.count(kind='EconomicFindingStudy')==1
        assert store.get('CONTROLLED-study')==old
        assert recovered.status()['shadow_realized_pnl'] is None
    finally:store.close()


def test_original_hash_and_clock_mismatch_fail_closed(tmp_path):
    store,index=setup(tmp_path)
    try:
        c=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=builder)
        index.entries[0]['forecast_sha256']='CONTROLLED-corrupt'
        with pytest.raises(ValueError,match='forecast hash'):c.step({})
        index.anchor['available_at']=(NOW+timedelta(seconds=1)).isoformat()
        with pytest.raises(ValueError,match='anchored source'):c.step({})
        assert store.count(kind='EconomicFindingStudy')==0
    finally:store.close()


def test_bootstrap_and_archive_backpressure_cannot_publish_partial_registry(tmp_path):
    store,index=setup(tmp_path);budget=[True]
    try:
        c=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:budget[0],builder=builder)
        index.caught_up=False;assert not c.step({})
        index.caught_up=True;budget[0]=False;assert not c.step({})
        assert store.count(kind='EconomicFindingStudy')==0
    finally:store.close()


def test_persisted_append_ahead_of_ack_is_adopted_without_duplicate(tmp_path,monkeypatch):
    store,index=setup(tmp_path)
    try:
        c=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=builder);append=store.append
        def interrupted(record):
            append(record)
            raise OSError('CONTROLLED interrupted acknowledgement')
        monkeypatch.setattr(store,'append',interrupted)
        with pytest.raises(OSError):c.step({})
        monkeypatch.setattr(store,'append',append)
        assert not c.step({}) and store.count(kind='EconomicFindingStudy')==1
        assert c.status()['totals']['evaluations']==1
    finally:store.close()


def test_authority_escalation_is_not_archived(tmp_path):
    store,index=setup(tmp_path)
    try:
        c=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=lambda *a,**k:{'research_only':True,'trading_authority':True})
        with pytest.raises(ValueError,match='authority'):c.step({})
        assert store.count(kind='EconomicFindingStudy')==0
    finally:store.close()


def test_current_full_book_evidence_is_lossless_and_recovery_rejects_corruption(tmp_path):
    from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
    store,index=setup(tmp_path)
    frame={'id':'CONTROLLED-frame','books':[{'id':'CONTROLLED-book','asks':[[.5,4]],'bids':[[.49,3]]}]}
    try:
        c=FindingsResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=builder)
        assert c.step(frame)
        row=store.latest('EconomicFindingStudy',1)[0]
        assert unpack_checkpoint(row['decision_frame'])==frame
        assert row['decision_frame_sha256']==digest(frame)
        bad=EconomicFindingStudy.model_validate(row).model_dump(mode='json')
        bad['decision_frame_sha256']='CONTROLLED-corrupt'
        with pytest.raises(ValueError,match='frame integrity'):c._adopt(bad)
    finally:store.close()
