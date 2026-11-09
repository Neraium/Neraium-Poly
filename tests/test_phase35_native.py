"""Synthetic controlled fixtures; never genuine market observations."""

import copy
import hashlib
import json

import pytest
from neraium_poly.research.phase35.native import (
    CTF,
    NEG_RISK,
    NativeResearchClient,
    call_key,
    replay_native_directory,
    verify_native_bundle,
    word,
)
from neraium_poly.research.settlement_evidence import CONDITION_RESOLUTION


def fixture_bundle():
    condition, question, block_hash, tx = ("0x" + str(i) * 64 for i in (1, 2, 3, 4))
    block = {"number": "0x64", "hash": block_hash, "timestamp": "0x6553f100"}
    final = {"number": "0x65", "hash": "0x" + "5" * 64, "timestamp": "0x6553f101"}
    log = {
        "address": CTF,
        "topics": [CONDITION_RESOLUTION, condition, "0x" + word(NEG_RISK), question],
        "data": "0x" + "".join(word(n) for n in (2, 64, 2, 0, 1)),
        "removed": False,
        "transactionHash": tx,
        "blockHash": block_hash,
        "blockNumber": "0x64",
        "logIndex": "0x1",
    }
    rules = "Official exact rule"
    market = {
        "market_id": "1",
        "event_id": "2",
        "question": "Question?",
        "token_id": "101",
        "outcome": "Yes",
        "resolution_rules": rules,
        "resolution_source": "https://official.example",
    }
    forecast = {
        "market_id": "1",
        "event_id": "2",
        "token_id": "101",
        "timestamp": "2023-11-13T00:00:00Z",
        "evidence_cutoff": "2023-11-12T00:00:00Z",
        "rules_sha256": hashlib.sha256(rules.encode()).hexdigest(),
        "market": market,
        "unconditional_contract_probability": False,
    }
    gamma = {
        "id": "1",
        "question": "Question?",
        "conditionId": condition,
        "description": rules,
        "resolutionSource": market["resolution_source"],
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["101","102"]',
        "closed": True,
        "umaResolutionStatus": "resolved",
        "version": "v1",
        "negRisk": True,
        "questionID": question,
    }
    state = []

    def add(target, name, args, value):
        target, data = call_key(target, name, *args)
        state.append({"to": target, "data": data, "block_hash": final["hash"], "result": "0x" + word(value)})

    collateral = "0x" + "6" * 40
    add(CTF, "condition", (NEG_RISK, question, 2), condition)
    add(NEG_RISK, "wrapped_collateral", (), collateral)
    for i in range(2):
        collection = "0x" + word(201 + i)
        add(CTF, "collection", ("0x" + "0" * 64, condition, 1 << i), collection)
        add(CTF, "position", (collateral, collection), 101 + i)
    add(CTF, "denominator", (condition,), 1)
    for i in range(2):
        add(CTF, "numerator", (condition, i), i)
    return {
        "forecast": forecast,
        "gamma": gamma,
        "clob": {"condition_id": condition, "primary_token_id": "101", "secondary_token_id": "102"},
        "parent_event": {"id": "2", "markets": [{"id": "1"}]},
        "log": log,
        "receipt": {
            "status": "0x1",
            "transactionHash": tx,
            "blockHash": block_hash,
            "blockNumber": "0x64",
            "logs": [log],
        },
        "block": block,
        "canonical_block": copy.deepcopy(block),
        "finalized": final,
        "available_at": "2023-11-15T00:00:00Z",
        "state": state,
    }


def test_finalized_negative_risk_asset_and_payout_binding():
    proof = verify_native_bundle(fixture_bundle())
    assert proof["payouts"] == [0, 1]
    assert proof["native_payout_verified"] is True
    assert proof["conditional_forecast"] is True
    assert proof["research_only"] is True
    assert proof["trading_authority"] is proof["certification_authority"] is False


@pytest.mark.parametrize(
    "defect",
    [
        "rules",
        "token",
        "question",
        "parent",
        "oracle",
        "unfinalized",
        "receipt",
        "initialization_locator",
        "condition",
        "position",
        "denominator",
        "numerator",
        "state_block",
        "future_forecast",
        "future_evidence",
        "new_generation",
        "source",
    ],
)
def test_fail_closed(defect):
    b = fixture_bundle()
    if defect == "rules":
        b["gamma"]["description"] += " amended"
    elif defect == "token":
        b["gamma"]["clobTokenIds"] = '["102","101"]'
    elif defect == "question":
        b["gamma"]["questionID"] = "0x" + "7" * 64
    elif defect == "parent":
        b["parent_event"]["markets"] = []
    elif defect == "oracle":
        b["log"]["topics"][2] = "0x" + "0" * 64
    elif defect == "unfinalized":
        b["finalized"]["number"] = "0x63"
    elif defect == "receipt":
        b["receipt"]["status"] = "0x0"
    elif defect == "initialization_locator":
        b["receipt"]["logs"] = []
    elif defect == "condition":
        b["state"][0]["result"] = "0x" + "0" * 64
    elif defect == "position":
        b["state"][3]["result"] = "0x" + word(999)
    elif defect == "denominator":
        b["state"][-3]["result"] = "0x" + word(2)
    elif defect == "numerator":
        b["state"][-1]["result"] = "0x" + word(0)
    elif defect == "state_block":
        b["state"][0]["block_hash"] = "0x" + "8" * 64
    elif defect == "future_forecast":
        b["forecast"]["timestamp"] = "2023-11-15T00:00:00Z"
    elif defect == "future_evidence":
        b["forecast"]["evidence_cutoff"] = "2023-11-14T00:00:00Z"
    elif defect == "new_generation":
        b["gamma"]["version"] = "v2"
    elif defect == "source":
        b["gamma"]["resolutionSource"] += "/wrong"
    with pytest.raises((ValueError, KeyError)):
        verify_native_bundle(b)


def test_mutated_raw_evidence_is_rejected(tmp_path):
    (tmp_path / "bundle.json").write_text(json.dumps(fixture_bundle()))
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/x.json").write_text("{}")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"responses": [{"response_path": "raw/x.json", "response_sha256": "0" * 64}]})
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_native_directory(tmp_path)


def test_no_transaction_or_arbitrary_contract_methods(tmp_path):
    c = NativeResearchClient(tmp_path)
    try:
        with pytest.raises(ValueError, match="only explicit"):
            c.request("eth_sendRawTransaction", ["0xdead"])
        with pytest.raises(ValueError, match="unreviewed"):
            c.call("0x" + "a" * 40, "condition", "0x" + "b" * 64, NEG_RISK, "0x" + "c" * 64, 2)
    finally:
        c.client.close()


@pytest.mark.parametrize('canonical', [False, None])
def test_state_replay_requires_explicit_canonical_block_request(tmp_path, canonical):
    import hashlib
    bundle = fixture_bundle()
    (tmp_path/'bundle.json').write_text(json.dumps(bundle))
    (tmp_path/'raw').mkdir()
    raw = json.dumps({'id': 1, 'result': '0x'+word(1)}).encode()
    (tmp_path/'raw/state.json').write_bytes(raw)
    block = {'blockHash': bundle['finalized']['hash']}
    if canonical is not None:
        block['requireCanonical'] = canonical
    (tmp_path/'manifest.json').write_text(json.dumps({'responses': [{
        'method':'POST','status':200,'response_path':'raw/state.json',
        'response_sha256':hashlib.sha256(raw).hexdigest(),
        'request':{'id':1,'method':'eth_call','params':[{'to':CTF,'data':'0x00'},block]}
    }]}))
    with pytest.raises(ValueError, match='explicit canonical finalized'):
        replay_native_directory(tmp_path)
