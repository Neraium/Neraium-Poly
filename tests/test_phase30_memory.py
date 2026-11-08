"""Controlled serialization fixtures, never market or performance evidence."""
import hashlib
import json
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.data.store import EventStore, _payload_metadata
from pydantic import Field

NOW=datetime(2026,11,8,tzinfo=UTC)


class CountingRecord(Record):
    serializations: ClassVar[int]=0
    evidence: list=Field(default_factory=list)
    qualified: object=None

    def model_dump_json(self,*args,**kwargs):
        type(self).serializations+=1
        return super().model_dump_json(*args,**kwargs)


def managed(path):
    return ManagedEventStore(path,segment_bytes=65536,budget_bytes=16*1024**2,min_free_bytes=0)


def record(**kw):
    return CountingRecord(id='CONTROLLED-exact',timestamp=NOW,available_at=NOW,source='CONTROLLED_fixture',**kw)


def test_managed_append_serializes_once_and_binds_exact_original_bytes(tmp_path):
    CountingRecord.serializations=0;r=record(evidence=[{'nested':[1,2,3],'unicode':'☃'}],qualified=True)
    expected=Record.model_dump_json(r);store=managed(tmp_path/'events.sqlite')
    try:
        assert store.append(r) and CountingRecord.serializations==1
        kind,payload,digest=store.get(r.id)
        assert kind=='CountingRecord' and payload==expected
        assert digest==hashlib.sha256(expected.encode()).hexdigest()
        assert store.count(qualified=True)==1
        assert not store.append(r) and CountingRecord.serializations==2
    finally:store.close()
    recovered=managed(tmp_path/'events.sqlite')
    try:assert recovered.get(r.id)[1]==expected and recovered.count()==1
    finally:recovered.close()


def test_prepared_payload_cannot_bypass_identity_or_json_validation(tmp_path):
    store=EventStore(tmp_path/'prepared.sqlite');r=record();payload=Record.model_dump_json(r)
    try:
        for bad in [payload.replace('CONTROLLED-exact','different'),payload[:-1]+',"nested":{"bad":[}}']:
            with pytest.raises(ValueError):store._append_payload(r.id,type(r).__name__,NOW.isoformat(),NOW.isoformat(),bad)
        assert store.count()==0
        assert store._append_payload(r.id,type(r).__name__,NOW.isoformat(),NOW.isoformat(),payload)
        changed=json.loads(payload);changed['source']='different'
        with pytest.raises(ValueError,match='collision'):store._append_payload(r.id,type(r).__name__,NOW.isoformat(),NOW.isoformat(),json.dumps(changed))
        assert store.count()==1 and store.get(r.id)[1]==payload
    finally:store.close()


@pytest.mark.parametrize('qualified,expected',[(True,1),(False,0),(None,-1),(1,-1),('true',-1),({'irrelevant':True},-1)])
def test_header_parser_preserves_qualified_boolean_semantics(qualified,expected):
    payload=Record.model_dump_json(record(qualified=qualified,evidence=[{'payload':[1,2,3]}]))
    assert _payload_metadata(payload,'CONTROLLED-exact',NOW.isoformat(),NOW.isoformat())==expected


@pytest.mark.parametrize('field,value',[('id','wrong'),('available_at','2027-01-01T00:00:00Z'),('timestamp','2027-01-01T00:00:00Z')])
def test_header_parser_rejects_original_metadata_mismatch(field,value):
    raw=json.loads(Record.model_dump_json(record()));raw[field]=value
    with pytest.raises(ValueError):_payload_metadata(json.dumps(raw),'CONTROLLED-exact',NOW.isoformat(),NOW.isoformat())
