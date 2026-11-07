"""Offline, default-deny replay of native settlement AND exact domain evidence.

No network calls, account writes, inferred final prices, new labels or trading
approval. Call in a worker thread when an asyncio loop is running, as required by
native proof replay. Existing immutable forecast/outcome studies remain unchanged.
"""

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase12.contracts import SettlementProofReference
from neraium_poly.research.phase12.outcome_collector import verify_collected_outcome
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.forecasting import map_event_contract
from neraium_poly.research.phase18.sources import completed_minutes
from neraium_poly.research.phase19.qualification import _label, _original, replay_event_forecast


def _at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_outcome_replay_time_required")
    return value.astimezone(UTC)


def _bounded(value):
    if not isinstance(value, dict):
        raise TypeError("canonical_study_mapping_required")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 2 * 1024**2:
        raise ValueError("bounded_outcome_replay_study_required")
    return json.loads(raw)


def _loss(probability, payout):
    likelihood = probability if payout else 1-probability
    return {"brier": (probability-payout)**2,
            "log_loss": -math.log(likelihood) if likelihood > 0 else None,
            "log_loss_status": "finite" if likelihood > 0 else "positive_infinity"}


def replay_crypto_outcome(outcome_study, original_study, *, evidence_root, as_of):
    """Reverify exact prospective identity, native finality and final Binance lows.

    Stored ``native_and_reference_verified`` flags and stored scores are not
    trusted. Native finalized CTF proofs are replayed from their immutable raw
    files; final reference candles are replayed from their original response bytes.
    Later retrieval is valid outcome evidence, never pre-forecast evidence.
    This verifies an individual label, not event independence or model calibration.
    """
    denied = {"verified": False, "research_only": True, "trading_authority": False,
              "certification_authority": False, "experimental_admission_authority": False}
    try:
        as_of = _at(as_of)
        original, labeled = _bounded(original_study), _bounded(outcome_study)
        if original.get("operation") != "forecast_scan" or labeled.get("operation") != "outcome_check":
            raise ValueError("original_forecast_and_outcome_operations_required")
        if any(row.get(key) for row in (original, labeled)
               for key in ("trading_authority", "certification_authority")):
            raise ValueError("research_study_authority_claim_forbidden")
        forecast, market, book, _evidence = _original(original)
        if not (forecast.timestamp <= _at(original["available_at"]) <= as_of
                and _at(labeled["timestamp"]) <= _at(labeled["available_at"]) <= as_of):
            raise ValueError("causal_original_and_outcome_studies_required")
        contract = DomainContract.model_validate(original["contract"])
        if contract.domain != "crypto" or contract.contract_type != "binance_daily_low_barrier":
            raise ValueError("exact_crypto_daily_low_outcome_supported_only")
        # Remap at the historical forecast cutoff, never at today's expired state.
        rebound = map_event_contract(market, now=forecast.evidence_cutoff)
        if (not rebound.compatible or rebound.review_required
                or rebound.parameters != contract.parameters
                or rebound.rules_sha256 != contract.rules_sha256):
            raise ValueError("original_exact_contract_replay_required")
        if replay_event_forecast(original).get("verified") is not True:
            raise ValueError("original_independent_model_replay_required")
        outcome = _label(labeled, original, forecast, market, as_of)
        start, end = map(_at, (contract.parameters["period_start_utc"],
                              contract.parameters["period_end_utc"]))
        if not forecast.timestamp < end <= outcome.settled_at:
            raise ValueError("completed_event_and_final_settlement_required")
        if not isinstance(labeled.get("evidence"), list) or len(labeled["evidence"]) != 1:
            raise ValueError("one_exact_final_reference_source_required")
        evidence = DomainEvidence.model_validate(labeled["evidence"][0])
        cutoff = _at(labeled["available_at"])
        payload = evidence.payload
        end_ms = int(end.timestamp()*1000)-1
        if (evidence.domain != contract.domain or payload.get("window_mode") != "resolution"
                or payload.get("end_ms") != end_ms
                or evidence.source_timestamp != datetime.fromtimestamp(end_ms/1000, UTC)
                or max(evidence.timestamp, evidence.available_at, evidence.retrieved_at) > cutoff
                or evidence.timestamp < end or _at(payload["requested_at"]) < end):
            raise ValueError("exact_final_reference_window_and_receipt_required")
        candles = completed_minutes(evidence, cutoff=cutoff,
                                    symbol=contract.parameters["symbol"], require_fresh=False)
        start_ms = int(start.timestamp()*1000)
        window = [c for c in candles if start_ms <= c["open_ms"] <= end_ms]
        if (not window or window[0]["open_ms"] != start_ms
                or window[-1]["close_ms"] != end_ms
                or len(window) != (end_ms+1-start_ms)//60000):
            raise ValueError("complete_exact_settlement_day_required")
        yes = int(min(c["low"] for c in window) <= contract.parameters["threshold"])
        payout = yes if contract.parameters["selected_outcome"] == "Yes" else 1-yes
        if outcome.payout != payout:
            raise ValueError("final_native_payout_and_reference_disagree")
        reference = SettlementProofReference(id=forecast.id, event_id=forecast.event_id,
            market_id=forecast.market_id, token_id=forecast.token_id,
            timestamp=forecast.timestamp, evidence_cutoff=forecast.evidence_cutoff,
            resolution_rules_sha256=forecast.rules_sha256,
            original_record_sha256=digest(original["forecast"]))
        root = Path(evidence_root)
        subdir = outcome.verification.get("acquisition_subdir")
        if (not isinstance(subdir, str) or not subdir or Path(subdir).name != subdir
                or root.is_symlink() or not root.is_dir() or (root/subdir).is_symlink()):
            raise ValueError("immutable_native_evidence_directory_required")
        if not verify_collected_outcome(outcome, market, reference, root):
            raise ValueError("native_finalized_raw_proof_replay_required")
        baseline = (book.bids[0].price+book.asks[0].price)/2
        return {**denied, "verified": True, "reason": None,
                "forecast_id": forecast.id, "event_id": forecast.event_id,
                "market_id": forecast.market_id, "token_id": forecast.token_id,
                "payout": payout, "settled_at": outcome.settled_at.isoformat(),
                "reference_available_at": evidence.available_at.isoformat(),
                "label_available_at": cutoff.isoformat(),
                "original_study_sha256": digest(original), "outcome_study_sha256": digest(labeled),
                "reference_sha256": evidence.content_sha256, "native_proof_sha256": outcome.proof_sha256,
                "reference_minutes": len(window), "forecast_score": _loss(forecast.probability, payout),
                "market_score": _loss(baseline, payout),
                "independence_reviewed": False, "calibration_supported": False,
                "performance_claim_supported": False}
    except (ValueError, TypeError, KeyError, OSError, OverflowError, IndexError, RuntimeError) as exc:
        return {**denied, "reason": str(exc)[:160] or type(exc).__name__}


def verify_crypto_outcome(outcome_study, original_study, *, evidence_root, as_of):
    """Boolean callback for the unchanged qualification_readiness authority gate."""
    return replay_crypto_outcome(outcome_study, original_study,
                                 evidence_root=evidence_root, as_of=as_of)["verified"] is True
