"""Controlled fixtures only; no fixture is a real resolution or profitable trade."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase20.outcomes import replay_crypto_outcome as completed_day_replay
from neraium_poly.research.phase21.outcomes import reference_condition, replay_crypto_outcome
from test_phase18_forecasting import CUTOFF, artifact
from test_phase20_outcomes import records


def early_records(*, side="Yes", crossed=True):
    original, label, _ = records(side=side, crossed=crossed)
    receipt = CUTOFF+timedelta(minutes=10)
    evidence = artifact(receipt)
    payload = deepcopy(evidence.payload)
    payload["window_mode"] = "forecast"
    if crossed:
        item = payload["responses"][-1]
        candles = json.loads(item["raw_response_utf8"])
        candles[-1][3] = "74000"
        raw = json.dumps(candles, separators=(",", ":"))
        item.update(raw_response_utf8=raw, raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest())
    evidence = evidence.model_copy(update={"payload": payload, "content_sha256": digest(payload)})
    native_at = receipt-timedelta(seconds=10)
    available = receipt+timedelta(seconds=10)
    label.update(timestamp=available.isoformat(), available_at=available.isoformat(),
                 evidence=[evidence.model_dump(mode="json")])
    label["outcome"].update(timestamp=native_at.isoformat(), settled_at=native_at.isoformat(),
                            available_at=available.isoformat())
    return original, label, available+timedelta(seconds=1)


@pytest.mark.parametrize("side", ["Yes", "No"])
def test_open_day_without_hit_is_pending_not_a_no_result(side):
    original, label, now = early_records(side=side, crossed=False)
    condition = reference_condition(original, label["evidence"][0], as_of=now)
    assert condition["status"] == "pending_no_completed_minute_hit"
    assert not condition["eligible_for_native_check"] and condition["selected_payout"] is None
    assert condition["underlying_yes"] is None and not condition["native_settlement_verified"]


@pytest.mark.parametrize("side,expected", [("Yes", 1), ("No", 0)])
def test_immediate_yes_is_only_a_native_check_candidate_until_finality(side, expected):
    original, label, now = early_records(side=side)
    condition = reference_condition(original, label["evidence"][0], as_of=now)
    assert condition["eligible_for_native_check"] and condition["underlying_yes"] == 1
    assert condition["selected_payout"] == expected and not condition["native_settlement_verified"]
    assert not condition["trading_authority"] and not condition["certification_authority"]


@pytest.mark.parametrize("side,expected", [("Yes", 1), ("No", 0)])
def test_early_native_settlement_requires_completed_hit_and_exact_original(tmp_path, monkeypatch, side, expected):
    original, label, now = early_records(side=side)
    before = deepcopy([original, label])
    calls = []
    monkeypatch.setattr("neraium_poly.research.phase21.outcomes.verify_collected_outcome",
                        lambda *args: calls.append(args) or True)
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert result["verified"] and result["payout"] == expected and len(calls) == 1
    assert result["resolution_mode"] == "immediate_yes_completed_minute_and_native_finality"
    assert result["first_hit_at"] < result["settled_at"] < original["market"]["end_time"]
    assert result["forecast_score"]["brier"] == (original["forecast"]["probability"]-expected)**2
    assert not result["calibration_supported"] and not result["performance_claim_supported"]
    assert [original, label] == before
    # Existing completed-day verifier would withhold this genuine rule variant.
    assert not completed_day_replay(label, original, evidence_root=tmp_path, as_of=now)["verified"]


def test_hit_after_native_settlement_does_not_corrobate_earlier_payout(tmp_path, monkeypatch):
    original, label, now = early_records()
    early = CUTOFF+timedelta(minutes=1)
    label["outcome"].update(timestamp=early.isoformat(), settled_at=early.isoformat())
    monkeypatch.setattr("neraium_poly.research.phase21.outcomes.verify_collected_outcome",
                        lambda *_args: pytest.fail("invalid reference must not reach native acceptance"))
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert not result["verified"] and result["reason"] == "completed_minute_hit_before_native_settlement_required"


def test_no_hit_before_close_cannot_become_final_no_or_yes(tmp_path, monkeypatch):
    original, label, now = early_records(crossed=False)
    monkeypatch.setattr("neraium_poly.research.phase21.outcomes.verify_collected_outcome", lambda *_args: True)
    assert not replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)["verified"]


def test_preforecast_corrected_hit_is_not_a_prospective_prediction():
    original, label, now = early_records()
    evidence = label["evidence"][0]
    payload = evidence["payload"]
    item = payload["responses"][0]
    rows = json.loads(item["raw_response_utf8"])
    rows[0][3] = "74000"
    raw = json.dumps(rows, separators=(",", ":"))
    item.update(raw_response_utf8=raw, raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest())
    evidence["content_sha256"] = digest(payload)
    result = reference_condition(original, evidence, as_of=now)
    assert not result["eligible_for_native_check"] and result["reason"] == "reference_condition_precedes_forecast"


@pytest.mark.parametrize("change", ["raw_hash", "timestamp", "future_receipt", "symbol", "threshold", "forecast"])
def test_unavailable_unbound_or_corrupted_source_never_makes_a_due_check(change):
    original, label, now = early_records()
    evidence = label["evidence"][0]
    if change == "raw_hash": evidence["payload"]["responses"][0]["raw_response_sha256"] = "0"*64
    if change == "timestamp": evidence["source_timestamp"] = CUTOFF.isoformat()
    if change == "future_receipt": evidence["retrieved_at"] = (now+timedelta(seconds=10)).isoformat()
    if change == "symbol": evidence["payload"]["symbol"] = "ETHUSDT"
    if change == "threshold": original["contract"]["parameters"]["threshold"] = 80000
    if change == "forecast": original["forecast"]["probability"] = .99
    result = reference_condition(original, evidence, as_of=now)
    assert not result["eligible_for_native_check"] and result["reason"]


def test_reference_hit_cannot_replace_missing_native_evidence(tmp_path, monkeypatch):
    original, label, now = early_records()
    monkeypatch.setattr("neraium_poly.research.phase21.outcomes.verify_collected_outcome", lambda *_: False)
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert not result["verified"] and result["reason"] == "native_finalized_raw_proof_replay_required"


@pytest.mark.parametrize("crossed", [True, False])
def test_full_day_final_outcome_reuses_existing_exact_replay(tmp_path, monkeypatch, crossed):
    original, label, now = records(crossed=crossed)
    monkeypatch.setattr("neraium_poly.research.phase20.outcomes.verify_collected_outcome", lambda *_: True)
    result = replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)
    assert result["verified"] and result["payout"] == int(crossed)


def test_naive_time_and_outcome_authority_claim_fail_closed(tmp_path):
    original, label, now = early_records()
    assert not reference_condition(original, label["evidence"][0], as_of=now.replace(tzinfo=None))["eligible_for_native_check"]
    label["trading_authority"] = True
    assert not replay_crypto_outcome(label, original, evidence_root=tmp_path, as_of=now)["verified"]


def test_unbounded_reference_payload_and_reordered_original_time_are_rejected():
    original, label, now = early_records()
    evidence = label["evidence"][0]
    evidence["payload"]["oversized"] = "x"*(2*1024**2)
    assert not reference_condition(original, evidence, as_of=now)["eligible_for_native_check"]
    original, label, now = early_records()
    original["timestamp"] = (now+timedelta(days=1)).isoformat()
    assert not reference_condition(original, label["evidence"][0], as_of=now)["eligible_for_native_check"]
