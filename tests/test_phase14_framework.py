"""Controlled orchestration fixtures, never authentic domain observations."""
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from neraium_poly.research.phase14 import framework
from test_phase14_finance import evidence


def test_invalid_worker_budget_and_existing_output_reject(tmp_path):
    for count in (0,3,True):
        with pytest.raises(ValueError,match="one or two"):
            framework.run_domain_research(tmp_path/'out',workers=count)
    with pytest.raises(ValueError,match="new unaliased"):
        framework.run_domain_research(tmp_path,workers=1)


def test_capture_hash_size_and_aliases_reject(tmp_path):
    path=tmp_path/'capture.json';path.write_text('{"CONTROLLED":true}')
    data,sha=framework.load_capture(path)
    assert data=={"CONTROLLED":True}
    with pytest.raises(ValueError,match="changed"):
        framework.load_capture(path,expected_sha256='0'*64)
    with pytest.raises(ValueError,match="bounded"):
        framework.load_capture(path,max_bytes=1)
    alias=tmp_path/'alias.json';alias.symlink_to(path)
    with pytest.raises(ValueError,match="aliases"):
        framework.load_capture(alias)
    os.link(path,tmp_path/'hardlink.json')
    with pytest.raises(ValueError,match="aliases"):
        framework.load_capture(path)
    assert len(sha)==64


def test_actual_source_payload_and_raw_hash_both_required():
    e=evidence()
    assert framework.verify_evidence(e.model_dump(mode='json')).id==e.id
    payload={**e.payload,'raw_response_sha256':'0'*64}
    changed=e.model_copy(update={'payload':payload,'content_sha256':framework.digest(payload)})
    with pytest.raises(ValueError,match="original source"):
        framework.verify_evidence(changed.model_dump(mode='json'))
    changed=e.model_copy(update={'content_sha256':'0'*64})
    with pytest.raises(ValueError,match="payload hash"):
        framework.verify_evidence(changed.model_dump(mode='json'))


def test_disk_floor_not_bypassed_even_for_test_output(tmp_path,monkeypatch):
    monkeypatch.setattr(framework.shutil,'disk_usage',lambda p:SimpleNamespace(free=0))
    with pytest.raises(ValueError,match="8GiB"):
        framework.run_domain_research(tmp_path/'out',workers=1)
    assert not (tmp_path/'out').exists()


def captures(tmp_path):
    root=tmp_path/'captures'
    for relative in framework.FILES.values():
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
    baseline=root/'baseline.json';baseline.write_text('{}')
    return root,baseline


def test_failed_study_publishes_no_success_artifact(tmp_path,monkeypatch):
    root,baseline=captures(tmp_path)
    monkeypatch.setattr(framework.shutil,'disk_usage',lambda p:SimpleNamespace(free=16*1024**3))
    def fail(*args):raise ValueError('CONTROLLED missing qualified evidence')
    monkeypatch.setattr(framework,'_worker',fail)
    with pytest.raises(ValueError,match="missing qualified"):
        framework.run_domain_research(tmp_path/'out',workers=1,capture_root=root,baseline_frame=baseline)
    assert not (tmp_path/'out').exists()


def test_serial_fixture_manifest_never_claims_parallelism_or_durable_dataset(tmp_path,monkeypatch):
    root,baseline=captures(tmp_path)
    monkeypatch.setattr(framework.shutil,'disk_usage',lambda p:SimpleNamespace(free=16*1024**3))
    def fake(name,*args):
        at=datetime(2026,1,1,tzinfo=UTC).isoformat()
        return {'CONTROLLED':name,'profitability':None},{'study':name,'pid':os.getpid(),'started_at':at,'completed_at':at}
    monkeypatch.setattr(framework,'_worker',fake)
    result=framework.run_domain_research(tmp_path/'out',workers=1,capture_root=root,baseline_frame=baseline)
    assert result['actual_overlapping_workers']==1 and result['durable_dataset'] is False
    assert result['forecasts_recorded']==0 and result['trading_authority'] is False
    loaded=json.loads((tmp_path/'out/manifest.json').read_text())
    assert loaded==result
