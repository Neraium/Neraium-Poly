"""Exact daily-barrier maturity and native replay, including immediate YES.

A completed source candle can make a native check eligible; it is never a
settlement. Underlying NO still needs the entire period and finalized native
proof. No ledger, model, account or P18 checkpoint is modified here.
"""

from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase12.contracts import SettlementProofReference
from neraium_poly.research.phase12.outcome_collector import verify_collected_outcome
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.forecasting import map_event_contract
from neraium_poly.research.phase18.sources import completed_minutes
from neraium_poly.research.phase19.qualification import _label, _original, replay_event_forecast
from neraium_poly.research.phase20.outcomes import _bounded, _loss
from neraium_poly.research.phase20.outcomes import replay_crypto_outcome as replay_completed_day

AUTHORITY = {"research_only": True, "trading_authority": False, "certification_authority": False,
             "experimental_admission_authority": False}


def _at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_reference_time_required")
    return value.astimezone(UTC)


def reference_condition(original_study, evidence, *, as_of):
    """Replay exact causal reference facts; never imply a finalized payout.

    Immediate YES means the selected NO token may eventually pay zero. That is
    distinct from an underlying NO result, which requires the completed day.
    ``first_hit_at`` is the qualifying minute's final close time, not an invented
    intraminute tick time. Source retrieval remains actual observed availability.
    """
    result = {"status": "withheld", "eligible_for_native_check": False,
              "underlying_yes": None, "selected_payout": None, "first_hit_at": None,
              "native_settlement_verified": False, **AUTHORITY}
    try:
        as_of = _at(as_of)
        original = _bounded(original_study)
        if original.get("operation") != "forecast_scan" or any(original.get(k) for k in
                ("trading_authority", "certification_authority")):
            raise ValueError("original_research_forecast_required")
        f, market, _book, _inputs = _original(original)
        if not (f.timestamp <= _at(original["available_at"]) <= as_of
                and _at(original["timestamp"]) <= _at(original["available_at"])):
            raise ValueError("available_prospective_original_required")
        c = DomainContract.model_validate(original["contract"])
        if c.domain != "crypto" or c.contract_type != "binance_daily_low_barrier":
            raise ValueError("exact_daily_low_contract_required")
        rebound = map_event_contract(market, now=f.evidence_cutoff)
        if (not rebound.compatible or rebound.parameters != c.parameters
                or rebound.rules_sha256 != c.rules_sha256
                or replay_event_forecast(original).get("verified") is not True):
            raise ValueError("original_exact_rule_and_model_replay_required")
        raw_evidence = evidence.model_dump(mode="json") if isinstance(evidence, DomainEvidence) else evidence
        e = DomainEvidence.model_validate(_bounded(raw_evidence))
        rows = completed_minutes(e, cutoff=as_of, symbol=c.parameters["symbol"], require_fresh=False)
        start, end = map(_at, (c.parameters["period_start_utc"], c.parameters["period_end_utc"]))
        start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
        if e.source_timestamp != datetime.fromtimestamp(e.payload["end_ms"]/1000, UTC):
            raise ValueError("exact_source_candle_timestamp_required")
        window = [r for r in rows if start_ms <= r["open_ms"] < end_ms]
        if not window or window[0]["open_ms"] != start_ms:
            raise ValueError("complete_elapsed_reference_window_required")
        hits = [r for r in window if r["low"] <= c.parameters["threshold"]]
        first_hit = datetime.fromtimestamp(hits[0]["close_ms"]/1000, UTC) if hits else None
        if first_hit and first_hit <= f.timestamp:
            raise ValueError("reference_condition_precedes_forecast")
        complete = window[-1]["close_ms"] == end_ms-1
        if not hits and (not complete or as_of < end):
            return {**result, "status": "pending_no_completed_minute_hit", "reason": None,
                    "period_end": end.isoformat(), "reference_end_at": e.source_timestamp.isoformat(),
                    "reference_available_at": e.available_at.isoformat(), "reference_sha256": e.content_sha256,
                    "reference_minutes": len(window), "forecast_id": f.id, "event_id": f.event_id}
        if not hits and (e.payload.get("window_mode") != "resolution" or e.payload["end_ms"] != end_ms-1):
            raise ValueError("exact_final_resolution_window_required")
        yes = int(bool(hits))
        payout = yes if c.parameters["selected_outcome"] == "Yes" else 1-yes
        return {**result, "status": "completed_minute_barrier_hit" if hits else "completed_day_no_hit",
                "reason": None, "eligible_for_native_check": True, "underlying_yes": yes,
                "selected_payout": payout, "first_hit_at": first_hit.isoformat() if first_hit else None,
                "period_end": end.isoformat(), "reference_end_at": e.source_timestamp.isoformat(),
                "reference_available_at": e.available_at.isoformat(), "reference_sha256": e.content_sha256,
                "reference_minutes": len(window), "forecast_id": f.id, "event_id": f.event_id,
                "market_id": f.market_id, "token_id": f.token_id}
    except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
        return {**result, "reason": str(exc)[:160] or type(exc).__name__}


def replay_crypto_outcome(outcome_study, original_study, *, evidence_root, as_of):
    """Require native finality plus pre-settlement qualifying completed-minute evidence.

    Full-day outcomes reuse the existing P20 replay unchanged. The additional
    branch permits only the rule's immediate underlying YES, never early NO.
    Native replay must run outside an asyncio loop (use a worker thread).
    """
    denied = {"verified": False, **AUTHORITY}
    try:
        as_of = _at(as_of)
        original, labeled = _bounded(original_study), _bounded(outcome_study)
        if labeled.get("operation") != "outcome_check" or any(labeled.get(k) for k in
                ("trading_authority", "certification_authority")):
            raise ValueError("original_forecast_and_research_outcome_required")
        f, market, book, _evidence = _original(original)
        if not (_at(labeled["timestamp"]) <= _at(labeled["available_at"]) <= as_of):
            raise ValueError("causal_outcome_study_required")
        outcome = _label(labeled, original, f, market, as_of)
        if outcome.settled_at >= market.end_time:
            return replay_completed_day(labeled, original, evidence_root=evidence_root, as_of=as_of)
        if not isinstance(labeled.get("evidence"), list) or len(labeled["evidence"]) != 1:
            raise ValueError("one_exact_independent_reference_required")
        condition = reference_condition(original, labeled["evidence"][0], as_of=_at(labeled["available_at"]))
        if (not condition["eligible_for_native_check"] or condition["underlying_yes"] != 1
                or not condition["first_hit_at"] or _at(condition["first_hit_at"]) > outcome.settled_at
                or condition["selected_payout"] != outcome.payout):
            raise ValueError("completed_minute_hit_before_native_settlement_required")
        reference = SettlementProofReference(id=f.id, event_id=f.event_id, market_id=f.market_id,
            token_id=f.token_id, timestamp=f.timestamp, evidence_cutoff=f.evidence_cutoff,
            resolution_rules_sha256=f.rules_sha256, original_record_sha256=digest(original["forecast"]))
        root = Path(evidence_root)
        subdir = outcome.verification.get("acquisition_subdir")
        if (not isinstance(subdir, str) or not subdir or Path(subdir).name != subdir
                or root.is_symlink() or not root.is_dir() or (root/subdir).is_symlink()):
            raise ValueError("immutable_native_evidence_directory_required")
        if not verify_collected_outcome(outcome, market, reference, root):
            raise ValueError("native_finalized_raw_proof_replay_required")
        baseline = (book.bids[0].price+book.asks[0].price)/2
        return {**denied, "verified": True, "reason": None, "forecast_id": f.id,
                "event_id": f.event_id, "market_id": f.market_id, "token_id": f.token_id,
                "payout": outcome.payout, "settled_at": outcome.settled_at.isoformat(),
                "resolution_mode": "immediate_yes_completed_minute_and_native_finality",
                "first_hit_at": condition["first_hit_at"], "reference_sha256": condition["reference_sha256"],
                "reference_available_at": condition["reference_available_at"],
                "label_available_at": labeled["available_at"], "reference_minutes": condition["reference_minutes"],
                "original_study_sha256": digest(original), "outcome_study_sha256": digest(labeled),
                "native_proof_sha256": outcome.proof_sha256, "forecast_score": _loss(f.probability, outcome.payout),
                "market_score": _loss(baseline, outcome.payout), "independence_reviewed": False,
                "calibration_supported": False, "performance_claim_supported": False}
    except (KeyError, TypeError, ValueError, OverflowError, OSError, IndexError, RuntimeError) as exc:
        return {**denied, "reason": str(exc)[:160] or type(exc).__name__}


def verify_crypto_outcome(outcome_study, original_study, *, evidence_root, as_of):
    return replay_crypto_outcome(outcome_study, original_study,
        evidence_root=evidence_root, as_of=as_of)["verified"] is True
