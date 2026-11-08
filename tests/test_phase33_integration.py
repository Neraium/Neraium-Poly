"""Controlled archival/derived-report flow, no actual trading evidence."""
import json
from datetime import timedelta

from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase28.continuous import VolumeStudy
from neraium_poly.research.phase32.pairs import PairResearch
from neraium_poly.research.phase33.continuous import FeeHeadroomResearch
from neraium_poly.research.phase33.storage import pack_dense_checkpoint
from test_phase24_integration import NOW
from test_phase33_economics import sample


def test_new_wire_hashes_bind_both_derived_records_and_restart_without_duplication(tmp_path):
    frame,_r,_o,_s=sample();raw=frame.model_dump(mode='json');store=EventStore(tmp_path/'controlled.sqlite')
    v=VolumeStudy(id='CONTROLLED-volume',timestamp=NOW,available_at=NOW,source='CONTROLLED',enrollment_id='CONTROLLED',evaluation_bucket=1,
        source_anchor={},decision_frame=pack_dense_checkpoint(raw),decision_frame_sha256=digest(raw),report={'findings':[],'padding':'CONTROLLED'*10000})
    try:
        store.append(v);source=json.loads(store.get(v.id)[1]);assert 'codec' in source['report']
        assert VolumeStudy.model_validate(source).report==v.report
        pair=PairResearch(store,clock=lambda:NOW,can_write=lambda:True);pair.observe(v,frame)
        pid=digest(['pair-study-v32',v.id,pair.report]);parent=json.loads(store.get(pid)[1])
        assert parent['volume_sha256']==digest(source)
        p=FeeHeadroomResearch(store,clock=lambda:NOW,can_write=lambda:True,observations=lambda _:{});p.observe(v,frame,pair.report)
        assert p.status()['status']=='research_fee_headroom' and p.status()['conservative_expected_net_profit'] is None
        record=store.latest('PairFeeStudy',limit=1)[0]
        assert record['source_pair_study_sha256']==digest(parent)
        again=FeeHeadroomResearch(store,clock=lambda:NOW+timedelta(seconds=1),can_write=lambda:True,observations=lambda _:{});again.observe(v,frame,pair.report)
        assert store.count(kind='PairFeeStudy')==1
        again.can_write=lambda:False;again.observe(v,frame,pair.report)
        assert again.status()['status']=='withheld' and 'findings' not in again.status()
        assert not again.status()['trading_authority']
    finally:store.close()


def test_uncommitted_pair_or_mismatched_volume_frame_cannot_be_annotated(tmp_path):
    frame,report,_o,_s=sample();store=EventStore(tmp_path/'controlled.sqlite')
    v=VolumeStudy(id='CONTROLLED',timestamp=NOW,available_at=NOW,source='CONTROLLED',enrollment_id='CONTROLLED',evaluation_bucket=1,
        source_anchor={},decision_frame=pack_dense_checkpoint(frame.model_dump(mode='json')),decision_frame_sha256=digest(frame.model_dump(mode='json')),report={})
    try:
        p=FeeHeadroomResearch(store,clock=lambda:NOW,can_write=lambda:True,observations=lambda _:{});p.observe(v,frame,report)
        assert p.status()['status']=='withheld' and store.count(kind='PairFeeStudy')==0
    finally:store.close()


def test_fee_publication_rejects_same_id_mutated_volume_or_future_parent(tmp_path):
    frame,_r,_o,_s=sample();raw=frame.model_dump(mode='json');store=EventStore(tmp_path/'controlled.sqlite')
    v=VolumeStudy(id='CONTROLLED',timestamp=NOW,available_at=NOW,source='CONTROLLED',enrollment_id='CONTROLLED',evaluation_bucket=1,
        source_anchor={},decision_frame=pack_dense_checkpoint(raw),decision_frame_sha256=digest(raw),report={})
    try:
        store.append(v);pairs=PairResearch(store,clock=lambda:NOW,can_write=lambda:True);pairs.observe(v,frame)
        changed=v.model_copy(update={'enrollment_id':'OTHER'})
        p=FeeHeadroomResearch(store,clock=lambda:NOW,can_write=lambda:True,observations=lambda _:{});p.observe(changed,frame,pairs.report)
        assert p.status()['status']=='withheld' and store.count(kind='PairFeeStudy')==0
        parent_id=digest(['pair-study-v32',v.id,pairs.report]);parent=json.loads(store.get(parent_id)[1]);parent['available_at']=(NOW+timedelta(seconds=1)).isoformat()
        class Proxy:
            def get(self,key):return parent if key==parent_id else store.get(key)
            def append(self,row):return store.append(row)
        p=FeeHeadroomResearch(Proxy(),clock=lambda:NOW,can_write=lambda:True,observations=lambda _:{});p.observe(v,frame,pairs.report)
        assert p.status()['status']=='withheld' and store.count(kind='PairFeeStudy')==0
    finally:store.close()
