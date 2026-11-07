"""Controlled unit evidence only; no fixture is an authentic settled market.

The native proof boundary is mocked here; existing Phase12 tests exercise raw
HTTP/CTF acquisition and replay. These tests exercise domain rebinding and final
external-evidence replay around that boundary.
"""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase14.contracts import DomainForecast
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.forecasting import forecast_event, map_event_contract
from neraium_poly.research.phase20.outcomes import replay_crypto_outcome, verify_crypto_outcome
from test_phase18_forecasting import CUTOFF, artifact, market


def records(*, side="Yes", crossed=False):
    m = market(outcome=side)
    c = map_event_contract(m, now=CUTOFF)
    e = artifact()
    result = forecast_event(c, (e,), cutoff=CUTOFF)
    b = OrderBookSnapshot(id="CONTROLLED book", timestamp=CUTOFF, available_at=CUTOFF,
        source="https://clob.polymarket.com", market_id=m.market_id, token_id=m.token_id,
        bids=(PriceLevel(price=.49, size=100),), asks=(PriceLevel(price=.51, size=100),))
    f = DomainForecast(id="CONTROLLED forecast", timestamp=CUTOFF, available_at=CUTOFF,
        source="CONTROLLED", domain=c.domain, event_id=c.event_id, market_id=c.market_id,
        token_id=c.token_id, contract_type=c.contract_type, probability_semantics=c.probability_semantics,
        probability=result["probability"], evidence_cutoff=CUTOFF, model_version=result["model_version"],
        model_sha256=result["model_sha256"], feature_version=result["feature_version"],
        dataset_sha256=result["dataset_sha256"], rules_sha256=c.rules_sha256,
        evidence_ids=tuple(result["evidence_ids"]), uncertainty=result["uncertainty"],
        calibration_status=result["calibration_status"], independent_of_polymarket=True,
        dependency_group="unreviewed CONTROLLED", contemporaneous_market={"market":m.model_dump(mode="json"),
            "book":b.model_dump(mode="json"), "contract":c.model_dump(mode="json")})
    original = {"id":"CONTROLLED original", "timestamp":CUTOFF.isoformat(),
        "available_at":CUTOFF.isoformat(), "operation":"forecast_scan", "forecast":f.model_dump(mode="json"),
        "market":m.model_dump(mode="json"), "book":b.model_dump(mode="json"),
        "contract":c.model_dump(mode="json"), "evidence":[e.model_dump(mode="json")], "model_result":result}
    settled = m.end_time+timedelta(seconds=10)
    received = m.end_time+timedelta(seconds=20)
    final = artifact(received)
    payload = deepcopy(final.payload)
    payload["window_mode"] = "resolution"
    if crossed:
        item = payload["responses"][-1]
        rows = json.loads(item["raw_response_utf8"])
        rows[-1][3] = "74000"
        raw = json.dumps(rows, separators=(",", ":"))
        item.update(raw_response_utf8=raw, raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest())
    final = final.model_copy(update={"payload":payload, "content_sha256":digest(payload)})
    reference = SettlementProofReference(id=f.id, event_id=f.event_id, market_id=f.market_id,
        token_id=f.token_id, timestamp=f.timestamp, evidence_cutoff=f.evidence_cutoff,
        resolution_rules_sha256=f.rules_sha256, original_record_sha256=digest(original["forecast"]))
    proof = {"forecast_id":f.id, "forecast_sha256":digest(reference.model_dump(mode="json")),
        "market_sha256":digest(m.model_dump(mode="json")), "acquisition_subdir":"CONTROLLED-proof"}
    payout = int(crossed) if side == "Yes" else 1-int(crossed)
    outcome = VerifiedEventOutcome(id="CONTROLLED outcome", timestamp=settled, available_at=received,
        source="CONTROLLED", event_id=f.event_id, market_id=f.market_id, token_id=f.token_id,
        payout=payout, resolution_rules_sha256=f.rules_sha256, settled_at=settled,
        verification_source="native_final_resolution_plus_finalized_ctf_raw_replay",
        proof_sha256=digest(proof), verification=proof)
    label = {"id":"CONTROLLED label", "timestamp":received.isoformat(), "available_at":received.isoformat(),
        "operation":"outcome_check", "forecast":deepcopy(original["forecast"]),
        "outcome":outcome.model_dump(mode="json"), "evidence":[final.model_dump(mode="json")],
        "model_result":{"status":"native_and_reference_verified", "reference_payout":payout,
            "individual_score":{"brier":999, "market_brier":999}}}
    return original, label, received+timedelta(seconds=1)


@pytest.fixture
def mocked_native(monkeypatch):
    calls = []
    def verify(*args):
        calls.append(args)
        return True
    monkeypatch.setattr("neraium_poly.research.phase20.outcomes.verify_collected_outcome", verify)
    return calls


@pytest.mark.parametrize("side,crossed", [("Yes",False),("No",False),("Yes",True),("No",True)])
def test_exact_source_replay_recomputes_individual_scores_without_mutation(tmp_path, mocked_native, side, crossed):
    original, label, now = records(side=side, crossed=crossed)
    before = deepcopy([original,label])
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert result["verified"], result
    assert len(mocked_native) == 1 and result["reference_minutes"] == 1440
    assert result["payout"] == label["outcome"]["payout"]
    assert result["forecast_score"]["brier"] == (original["forecast"]["probability"]-result["payout"])**2
    assert result["market_score"]["brier"] == .25
    assert not result["performance_claim_supported"] and not result["calibration_supported"]
    assert not result["trading_authority"] and not result["certification_authority"]
    assert [original,label] == before
    assert verify_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)


@pytest.mark.parametrize("change", ["token", "question", "threshold", "rules", "forecast", "status",
    "native_payout", "source_hash", "raw_hash", "source_time", "receipt", "symbol", "mode",
    "request_end", "window_end", "future_label", "authority", "operation", "settled_early"])
def test_corrupted_or_unbound_labels_never_qualify(tmp_path, mocked_native, change):
    original, label, now = records()
    if change == "token": label["outcome"]["token_id"] = "unrelated"
    if change == "question": original["market"]["question"] = "unrelated exact contract?"
    if change == "threshold": original["contract"]["parameters"]["threshold"] = 1
    if change == "rules": original["market"]["resolution_rules"] += " changed"
    if change == "forecast": label["forecast"]["probability"] = .9
    if change == "status": label["model_result"]["status"] = "disputed"
    if change == "native_payout":
        label["outcome"]["payout"] = 1
        label["model_result"]["reference_payout"] = 1
    if change == "source_hash": label["evidence"][0]["content_sha256"] = "0"*64
    if change == "raw_hash": label["evidence"][0]["payload"]["responses"][0]["raw_response_sha256"] = "0"*64
    if change == "source_time": label["evidence"][0]["source_timestamp"] = CUTOFF.isoformat()
    if change == "receipt": label["evidence"][0]["retrieved_at"] = (now+timedelta(seconds=1)).isoformat()
    if change == "symbol": label["evidence"][0]["payload"]["symbol"] = "ETHUSDT"
    if change == "mode": label["evidence"][0]["payload"]["window_mode"] = "forecast"
    if change == "request_end": label["evidence"][0]["payload"]["responses"][0]["request"]["endTime"] -= 60000
    if change == "window_end": label["evidence"][0]["payload"]["end_ms"] -= 60000
    if change == "future_label": label["available_at"] = (now+timedelta(seconds=1)).isoformat()
    if change == "authority": label["trading_authority"] = True
    if change == "operation": label["operation"] = "temporary_quote"
    if change == "settled_early":
        label["outcome"]["settled_at"] = (CUTOFF+timedelta(seconds=1)).isoformat()
        label["outcome"]["timestamp"] = label["outcome"]["settled_at"]
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert not result["verified"] and result["reason"]
    assert not mocked_native


def test_unavailable_or_disputed_native_proofs_are_not_replaced_by_external_candles(tmp_path, monkeypatch):
    original, label, now = records()
    monkeypatch.setattr("neraium_poly.research.phase20.outcomes.verify_collected_outcome", lambda *_:False)
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert result["reason"] == "native_finalized_raw_proof_replay_required"
    assert not result["verified"]


def test_without_actual_native_archive_self_declared_verified_flag_is_insufficient(tmp_path):
    original, label, now = records()
    assert not verify_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)


def test_bounds_naive_time_and_proof_directory_escape_deny(tmp_path, mocked_native):
    original, label, now = records()
    assert not verify_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now.replace(tzinfo=None))
    label["outcome"]["verification"]["acquisition_subdir"] = "../escape"
    label["outcome"]["proof_sha256"] = digest(label["outcome"]["verification"])
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert result["reason"] == "immutable_native_evidence_directory_required" and not mocked_native
    original["oversized"] = "x"*(2*1024**2)
    assert not verify_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
