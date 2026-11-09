"""Controlled persistence/restart tests; fixtures are not market evidence."""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase35 import persistence as p

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def setup(tmp_path, monkeypatch):
    store = EventStore(tmp_path/'controlled.sqlite')
    root = tmp_path/'proofs';folder = root/'reviewed';folder.mkdir(parents=True)
    f = {'id':'forecast','timestamp':(NOW-timedelta(days=2)).isoformat()}
    study = {'id':'study','forecasts':[f]}
    proof = {'market_id':'market','event_id':'event','settlement_at':(NOW-timedelta(days=1)).isoformat(), 'available_at':NOW.isoformat()}
    (folder/'bundle.json').write_text(json.dumps({'forecast':f}))
    (folder/'manifest.json').write_text('{}')
    entry = {'directory':'reviewed',**{name+'_sha256':hashlib.sha256((folder/(name+'.json')).read_bytes()).hexdigest() for name in ('bundle','manifest')}}
    (root/'inventory.json').write_text(json.dumps([entry]))
    real_latest = p.latest
    label = {'forecast_id':'forecast','original_forecast_sha256':digest(f),'original_study_id':'study','original_study_sha256':digest(study)}
    monkeypatch.setattr(p,'latest',lambda s,k,limit: [label] if k=='OfficialEventLabelStudy' else real_latest(s,k,limit))
    monkeypatch.setattr(p,'original',lambda s,i:deepcopy(study))
    monkeypatch.setattr(p,'replay_native_directory',lambda path:deepcopy(proof))
    monkeypatch.setattr(p,'callbacks',lambda *a:(lambda s,f,**k: {'verified':True,'forecast_sha256':digest(f),'original_study_sha256':digest(s)},None))
    return store, root, folder, proof


def test_append_only_restart_idempotence(tmp_path,monkeypatch):
    store,root,_folder,_proof=setup(tmp_path,monkeypatch)
    try:
        engine=p.NativeResearchPublisher(store,root,clock=lambda:NOW,can_write=lambda:True)
        assert engine.step()['native_verified_markets']==1
        assert store.count(kind='NativePayoutResearchStudy')==1
        restored=p.NativeResearchPublisher(store,root,clock=lambda:NOW,can_write=lambda:True)
        assert restored.step()['native_forecast_bindings']==1
        assert store.count(kind='NativePayoutResearchStudy')==1
        assert restored.status()['trading_authority'] is False
    finally:store.close()


@pytest.mark.parametrize('failure',['backpressure','hash','future','source'])
def test_fail_closed(tmp_path,monkeypatch,failure):
    store,root,folder,proof=setup(tmp_path,monkeypatch)
    try:
        if failure=='hash':(folder/'bundle.json').write_text('{}')
        if failure=='future':proof['settlement_at']=(NOW+timedelta(days=1)).isoformat()
        if failure=='source':monkeypatch.setattr(p,'original',lambda *a:{'id':'wrong','forecasts':[]})
        engine=p.NativeResearchPublisher(store,root,clock=lambda:NOW,can_write=lambda:failure!='backpressure')
        with pytest.raises(ValueError):engine.step()
        assert store.count(kind='NativePayoutResearchStudy')==0
    finally:store.close()


def test_no_inventory_is_explicit(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite')
    try:
        engine=p.NativeResearchPublisher(store,tmp_path/'absent',clock=lambda:NOW,can_write=lambda:True)
        assert engine.step()['blocker']=='native_evidence_inventory_unavailable'
        assert store.count()==0
    finally:store.close()
