"""Controlled serialization/recovery fixtures, never evidence of market profit."""
import base64
import hashlib
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase28.continuous import VolumeStudy
from neraium_poly.research.phase33.storage import decode_report, encode_report, pack_dense_checkpoint
from test_phase24_integration import NOW, inputs
from test_phase28_continuous import VolumeResearch, build, combine, setup


def study():
    frame=inputs()[-1].model_dump(mode='json');report={'findings':[{'forecast':'CONTROLLED','reason':'unsupported'*40} for _ in range(100)],'research_only':True,'trading_authority':False}
    return VolumeStudy(id='CONTROLLED-volume',timestamp=NOW,available_at=NOW,source='CONTROLLED-fixture',
        enrollment_id='CONTROLLED',evaluation_bucket=1,source_anchor={},decision_frame=pack_checkpoint(frame),
        decision_frame_sha256=digest(frame),report=report),report


def test_report_wire_is_lossless_and_model_dump_matches_actual_stored_payload(tmp_path):
    row,logical=study();store=EventStore(tmp_path/'CONTROLLED.sqlite')
    try:
        assert row.report==logical
        assert row.model_dump(mode='json')['report']['codec']
        assert store.append(row)
        kind,payload,sha=store.get(row.id)
        assert kind=='VolumeStudy' and hashlib.sha256(payload.encode()).hexdigest()==sha
        assert digest(json.loads(payload))==digest(row.model_dump(mode='json'))
        recovered=VolumeStudy.model_validate_json(payload)
        assert recovered.report==logical and recovered.model_dump(mode='json')==row.model_dump(mode='json')
        assert not store.append(recovered)
    finally:store.close()


def test_legacy_plaintext_is_readable_without_rewriting_original_bytes(tmp_path):
    row,logical=study();raw=row.model_dump(mode='json');raw['report']=logical
    payload=json.dumps(raw,separators=(',',':'));store=EventStore(tmp_path/'CONTROLLED-legacy.sqlite')
    try:
        store._append_payload(row.id,'VolumeStudy',NOW.isoformat(),NOW.isoformat(),payload)
        before=store.get(row.id)
        assert VolumeStudy.model_validate_json(before[1]).report==logical
        assert store.get(row.id)==before  # Reading must never rewrite a legacy source.
    finally:store.close()


@pytest.mark.parametrize('fault',['raw_hash','gzip_hash','base64','declared_size','trailing','unknown_codec'])
def test_corrupt_or_oversized_report_envelope_fails_closed(fault):
    value=encode_report({'evidence':['CONTROLLED'*200]*100});assert 'codec' in value
    bad=deepcopy(value)
    if fault=='raw_hash':bad['raw_sha256']='0'*64
    elif fault=='gzip_hash':bad['gzip_sha256']='0'*64
    elif fault=='base64':bad['gzip_base64']='!'+bad['gzip_base64'][1:]
    elif fault=='declared_size':bad['raw_bytes']=9*1024**2
    elif fault=='unknown_codec':bad['codec']='unknown'
    else:
        packed=base64.b64decode(bad['gzip_base64'])+b'TRAILING'
        bad.update(gzip_base64=base64.b64encode(packed).decode(),gzip_bytes=len(packed),gzip_sha256=hashlib.sha256(packed).hexdigest())
    with pytest.raises(ValueError):decode_report(bad)


def test_small_or_incompressible_reports_keep_plain_shape_and_finite_json_contract():
    value={'small':'CONTROLLED'};assert encode_report(value)==value and decode_report(value)==value
    with pytest.raises(ValueError):encode_report({'nonfinite':float('nan')})
    with pytest.raises(ValueError):decode_report({'body':'a'*(9*1024**2)})


def test_dense_frame_reconstructs_identical_source_and_reduces_repeated_structure():
    raw={'source':'CONTROLLED','observations':[{'id':str(i),'rules':'CONTROLLED'*500} for i in range(200)]}
    old=pack_checkpoint(raw);new=pack_dense_checkpoint(raw)
    assert unpack_checkpoint(new)==unpack_checkpoint(old)==raw
    assert new['raw_sha256']==old['raw_sha256'] and new['gzip_bytes']<old['gzip_bytes']


def test_new_checkpoint_recovery_retains_full_logical_report_and_no_duplicate_volume(tmp_path):
    store,index=setup(tmp_path)
    try:
        r=VolumeResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=build,combiner=combine)
        assert r.step({'books':[]})
        recovered=VolumeResearch(store,index,clock=lambda:NOW+timedelta(seconds=1),can_write=lambda:True,builder=build,combiner=combine)
        assert not recovered.step({'books':[]}) and store.count(kind='VolumeStudy')==1
        assert recovered.status()['totals']==r.status()['totals']
    finally:store.close()


def test_interrupted_encoding_commits_no_partial_volume_and_retry_is_idempotent(tmp_path,monkeypatch):
    from neraium_poly.research.phase28 import continuous
    store,index=setup(tmp_path)
    try:
        runtime=VolumeResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=build,combiner=combine)
        original=continuous.encode_report
        def interrupted(_value):raise OSError('CONTROLLED encoding interruption')
        monkeypatch.setattr(continuous,'encode_report',interrupted)
        with pytest.raises(Exception,match='CONTROLLED encoding interruption'):runtime.step({'books':[]})
        assert store.count(kind='VolumeStudy')==0 and runtime.last_bucket is None
        monkeypatch.setattr(continuous,'encode_report',original)
        assert runtime.step({'books':[]}) and not runtime.step({'books':[]})
        assert store.count(kind='VolumeStudy')==1
    finally:store.close()
