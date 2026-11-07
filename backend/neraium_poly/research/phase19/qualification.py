"""Default-deny qualification of original prospective studies and verified labels.

Callbacks replay the archive/native evidence outside this pure adapter. Their results
cannot grant trading or certification authority. Original records are never changed.
"""

import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlsplit

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence, DomainForecast
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.validation import event_disjoint_validation


def _at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_qualification_time_required")
    return value.astimezone(UTC)


def _review(callback, *records):
    if not callable(callback):
        return None
    try:
        return callback(*deepcopy(records))
    except Exception:  # noqa: BLE001 - unavailable independent replay cannot qualify a row
        return None


def _original(study):
    f = DomainForecast.model_validate(study["forecast"])
    c = DomainContract.model_validate(study["contract"])
    m = MarketSnapshot.model_validate(study["market"])
    b = OrderBookSnapshot.model_validate(study["book"])
    context = {"market": m.model_dump(mode="json"), "book": b.model_dump(mode="json"),
               "contract": c.model_dump(mode="json")}
    if f.contemporaneous_market != context:
        raise ValueError("original_forecast_context_changed")
    if len({(x.event_id, x.market_id, x.token_id) for x in (f, c, m)}) != 1:
        raise ValueError("forecast_event_market_token_mismatch")
    if (not f.independent_of_polymarket or f.probability_semantics != "binary_event_probability"
        or not c.compatible or c.review_required or c.probability_semantics != f.probability_semantics
        or c.domain != f.domain or c.contract_type != f.contract_type):
        raise ValueError("independent_reviewed_binary_contract_required")
    if (m.source != "https://gamma-api.polymarket.com" or m.exchange != "polymarket"
        or m.status != "active" or not m.end_time or m.end_time <= f.timestamp
        or b.market_id != m.market_id or b.exchange != m.exchange or b.source not in PUBLIC_BOOK_SOURCES
        or not assess_book(b, f.timestamp, max_spread=.05, expected_token=f.token_id).healthy):
        raise ValueError("original_executable_market_baseline_required")
    if (not m.resolution_rules or not m.resolution_source
        or sha256(m.resolution_rules.encode()).hexdigest() != f.rules_sha256
        or c.rules_sha256 != f.rules_sha256):
        raise ValueError("original_resolution_rule_binding_required")
    if not (m.timestamp <= m.available_at <= f.evidence_cutoff <= f.timestamp <= f.available_at
            <= _at(study["available_at"])):
        raise ValueError("nonprospective_forecast_context")
    if c.available_at > f.evidence_cutoff or c.timestamp > f.evidence_cutoff:
        raise ValueError("future_contract_interpretation")
    selected = [DomainEvidence.model_validate(x) for x in study["evidence"]]
    for e in selected:
        origin = urlsplit(e.source)
        if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.hostname == "polymarket.com" or origin.hostname.endswith(".polymarket.com")):
            raise ValueError("independent_external_source_origin_required")
    if (len({e.id for e in selected}) != len(selected) or tuple(e.id for e in selected) != f.evidence_ids
        or any(e.domain != f.domain or not e.independent_of_polymarket
               or e.qualification != "qualified_research" or digest(e.payload) != e.content_sha256
               or max(e.available_at, e.retrieved_at, e.timestamp) > f.evidence_cutoff for e in selected)):
        raise ValueError("original_causal_external_evidence_required")
    result = study["model_result"]
    if (result.get("status") != "research_estimate" or result.get("independent_of_polymarket") is not True
        or any(result.get(k) != getattr(f, k) for k in
               ("domain", "contract_type", "event_id", "market_id", "token_id", "rules_sha256",
                "model_version", "model_sha256", "dataset_sha256", "feature_version", "probability_semantics"))
        or type(result.get("probability")) not in (int, float)
        or abs(result["probability"]-f.probability) > 1e-12
        or tuple(result.get("evidence_ids", ())) != f.evidence_ids
        or _at(result["evidence_cutoff"]) != f.evidence_cutoff
        or result.get("uncertainty") != f.uncertainty):
        raise ValueError("original_model_result_binding_required")
    return f, m, b, selected


def _label(study, original, forecast, market, as_of):
    if digest(study["forecast"]) != digest(original["forecast"]):
        raise ValueError("outcome_forecast_not_original")
    outcome = VerifiedEventOutcome.model_validate(study["outcome"])
    if ((outcome.event_id, outcome.market_id, outcome.token_id) !=
            (forecast.event_id, forecast.market_id, forecast.token_id)
        or outcome.resolution_rules_sha256 != forecast.rules_sha256):
        raise ValueError("outcome_identity_or_rules_mismatch")
    if not (forecast.timestamp < outcome.settled_at == outcome.timestamp <= outcome.available_at
            <= _at(study["available_at"]) <= as_of):
        raise ValueError("outcome_availability_or_settlement_time_invalid")
    reference = SettlementProofReference(id=forecast.id, event_id=forecast.event_id,
        market_id=forecast.market_id, token_id=forecast.token_id, timestamp=forecast.timestamp,
        evidence_cutoff=forecast.evidence_cutoff, resolution_rules_sha256=forecast.rules_sha256,
        original_record_sha256=digest(original["forecast"]))
    proof = outcome.verification
    if (outcome.verification_source != "native_final_resolution_plus_finalized_ctf_raw_replay"
        or digest(proof) != outcome.proof_sha256 or proof.get("forecast_id") != forecast.id
        or proof.get("forecast_sha256") != digest(reference.model_dump(mode="json"))
        or proof.get("market_sha256") != digest(market.model_dump(mode="json"))
        or study.get("model_result", {}).get("status") != "native_and_reference_verified"
        or study["model_result"].get("reference_payout") != outcome.payout):
        raise ValueError("native_and_reference_bound_outcome_required")
    return outcome


def qualification_readiness(studies, *, as_of, training_end, heldout_start,
                            verify_forecast=None, verify_outcome=None, review_group=None):
    """Adapt recorded studies to the unchanged100/100event-disjoint validator.

    ``verify_forecast(original_study)`` must return ``{verified: True,
    model_training_cutoff: <independently replayed artifact time>}``.
    ``verify_outcome(outcome_study, original_study)`` must replay native AND
    independent reference evidence and return exactly True. ``review_group``
    returns ``{reviewed: True, dependency_group: <reviewed ID>}`` for an original
    study. Missing callbacks deny; a model's own flags cannot verify it.

    Counts cover the supplied bounded snapshot only. Eligible original rows can
    remain pending or uncalibrated. No price marks, inferred labels, current books
    or invented model-training timestamps are substituted for missing evidence.
    """
    as_of, training_end, heldout_start = map(_at, (as_of, training_end, heldout_start))
    if not training_end < heldout_start <= as_of:
        raise ValueError("ordered_predeclared_split_required")
    if not isinstance(studies, (tuple, list)) or len(studies) > 4096:
        raise ValueError("bounded_study_snapshot_required")
    records, size = [], 0
    for raw in studies:
        if not isinstance(raw, dict):
            raise TypeError("canonical_study_mappings_required")
        encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        size += len(encoded)
        if len(encoded) > 2*1024**2 or size > 128*1024**2:
            raise ValueError("bounded_study_bytes_required")
        records.append(json.loads(encoded))
    rejected, counts, originals, conflicts, outcome_studies = Counter(), Counter(), {}, set(), []
    scan_rejections = Counter()
    hashes = sorted(digest(r) for r in records)
    for study in sorted(records, key=lambda r: str(r.get("available_at", ""))):
        counts["studies"] += 1
        try:
            if not _at(study["timestamp"]) <= _at(study["available_at"]) <= as_of:
                raise ValueError("study_future_or_reordered_availability")
            if study.get("trading_authority") or study.get("certification_authority"):
                raise ValueError("study_authority_claim_forbidden")
            if study.get("operation") == "policy_transition":
                counts["policy_transitions"] += 1
                continue
            if study.get("operation") == "outcome_check":
                if study.get("outcome") is not None:
                    outcome_studies.append(study)
                else:
                    counts["unresolved_outcome_checks"] += 1
                continue
            if study.get("operation") != "forecast_scan":
                raise ValueError("unsupported_study_operation")
            if study.get("forecast") is None:
                counts["withheld_scans"] += 1
                observed = study.get("scan", {}).get("rejections", {})
                if isinstance(observed, dict):
                    for reason, count in list(observed.items())[:128]:
                        if isinstance(reason, str) and type(count) is int and 0 <= count <= 10000:
                            key = reason[:120] if reason[:120] in scan_rejections or len(scan_rejections) < 128 else "other_bounded_scan_rejections"
                            scan_rejections[key] += count
                for reason in study.get("model_result", {}).get("reasons", [])[:32]:
                    if isinstance(reason, str):
                        key = reason[:120] if reason[:120] in scan_rejections or len(scan_rejections) < 128 else "other_bounded_scan_rejections"
                        scan_rejections[key] += 1
                continue
            forecast, market, book, evidence = _original(study)
            previous = originals.get(forecast.id)
            if previous:
                if digest(previous[0]["forecast"]) != digest(study["forecast"]):
                    conflicts.add(forecast.id)
                else:
                    counts["duplicate_original_records"] += 1
                continue
            originals[forecast.id] = study, forecast, market, book, evidence
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected[str(exc)[:120] if isinstance(exc, ValueError) else "malformed_study_record"] += 1
    for fid in conflicts:
        originals.pop(fid, None)
        rejected["conflicting_original_forecast_id"] += 1
    counts["original_forecasts"] = len(originals)
    labels, claims = defaultdict(list), defaultdict(set)
    for study in outcome_studies:
        try:
            fid = study["forecast"]["id"]
            if fid not in originals:
                raise ValueError("outcome_original_forecast_not_in_snapshot")
            origin, forecast, market, _book, _evidence = originals[fid]
            outcome = _label(study, origin, forecast, market, as_of)
            claims[fid].add(outcome.payout)
            counts["recorded_outcome_matches"] += 1
            if _review(verify_outcome, study, origin) is not True:
                raise ValueError("independent_native_and_reference_replay_required")
            labels[fid].append((outcome, study))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected[str(exc)[:120] if isinstance(exc, ValueError) else "malformed_outcome_record"] += 1
    for fid, payouts in claims.items():
        if len(payouts) > 1:
            labels.pop(fid, None)
            rejected["conflicting_recorded_outcome_claims"] += 1
    # Freeze group coverage BEFORE looking at which labels happened to arrive.
    # Otherwise an unresolved earliest forecast or training event can disappear,
    # allowing outcome-dependent selection or a falsely event-disjoint holdout.
    reviews, earliest, coverage = {}, {}, defaultdict(set)
    parent_groups, unresolved_groups = defaultdict(set), set()
    for fid, (study, forecast, _market, _book, _evidence) in sorted(
            originals.items(), key=lambda item: (item[1][1].timestamp, item[0])):
        reviewed = _review(verify_forecast, study)
        group = _review(review_group, study)
        reviews[fid] = reviewed, group
        if (not isinstance(reviewed, dict) or reviewed.get("verified") is not True
            or not isinstance(group, dict) or group.get("reviewed") is not True
            or not isinstance(group.get("dependency_group"), str)
            or not 1 <= len(group["dependency_group"]) <= 256):
            continue
        dependency = group["dependency_group"]
        cohort = (forecast.domain, forecast.contract_type, forecast.model_version,
                  forecast.model_sha256, forecast.feature_version, dependency)
        earliest.setdefault(cohort, fid)
        partition = "train" if forecast.timestamp <= training_end else "validation" if forecast.timestamp < heldout_start else "heldout"
        coverage[dependency].add(partition)
        parent_groups[forecast.event_id].add(dependency)
        if fid not in labels:
            unresolved_groups.add(dependency)
    rows, reviewed_parents = [], set()
    for fid, (study, forecast, market, book, evidence) in sorted(originals.items()):
        reviewed, group = reviews[fid]
        raw_verified = isinstance(reviewed, dict) and reviewed.get("verified") is True
        group_verified = (isinstance(group, dict) and group.get("reviewed") is True
            and isinstance(group.get("dependency_group"), str) and 1 <= len(group["dependency_group"]) <= 256)
        if raw_verified:
            counts["source_replayed_forecasts"] += 1
        else:
            rejected["independent_forecast_source_replay_required"] += 1
        if group_verified:
            reviewed_parents.add(forecast.event_id)
        else:
            rejected["reviewed_parent_dependency_group_required"] += 1
        if fid not in labels:
            rejected["independently_verified_outcome_pending"] += 1
        if not raw_verified or not group_verified or fid not in labels:
            continue
        dependency = group["dependency_group"]
        cohort = (forecast.domain, forecast.contract_type, forecast.model_version,
                  forecast.model_sha256, forecast.feature_version, dependency)
        if len(parent_groups[forecast.event_id]) != 1:
            rejected["same_parent_has_inconsistent_dependency_groups"] += 1
            continue
        if earliest[cohort] not in labels:
            rejected["earliest_prospective_group_forecast_outcome_pending"] += 1
            continue
        # Existing fully labeled overlap is handled by the unchanged validator;
        # retain unresolved split exposure too, which has no fabricated row/label.
        if ("heldout" in coverage[dependency] and len(coverage[dependency]) > 1
            and dependency in unresolved_groups):
            rejected["unresolved_event_group_seen_before_heldout"] += 1
            continue
        try:
            trained = _at(reviewed["model_training_cutoff"])
        except (KeyError, TypeError, ValueError):
            rejected["verified_model_training_cutoff_required"] += 1
            continue
        if trained > forecast.evidence_cutoff:
            rejected["model_training_artifact_after_forecast_cutoff"] += 1
            continue
        outcome, labeled = min(labels[fid], key=lambda x: (_at(x[1]["available_at"]), x[0].id))
        rows.append({"forecast_id": fid, "event_id": forecast.event_id,
            "market_id": forecast.market_id, "token_id": forecast.token_id,
            "dependency_group": group["dependency_group"], "independence_reviewed": True,
            "domain": forecast.domain, "contract_type": forecast.contract_type,
            "model_version": forecast.model_version, "model_sha256": forecast.model_sha256,
            "feature_version": forecast.feature_version, "dataset_sha256": forecast.dataset_sha256,
            "forecast_sha256": digest(study["forecast"]), "outcome_proof_sha256": outcome.proof_sha256,
            "original_study_sha256": digest(study), "outcome_study_sha256": digest(labeled),
            "resolution_rules": market.resolution_rules, "resolution_rules_sha256": forecast.rules_sha256,
            "outcome_rules_sha256": outcome.resolution_rules_sha256,
            "probability_semantics": "binary_terminal_event_probability", "uses_market_features": False,
            "forecast_at": forecast.timestamp.isoformat(), "recorded_at": study["available_at"],
            "evidence_cutoff": forecast.evidence_cutoff.isoformat(),
            "evidence_available_at": max(e.available_at for e in evidence).isoformat(),
            "model_training_cutoff": trained.isoformat(), "market_at": book.timestamp.isoformat(),
            "market_available_at": book.available_at.isoformat(), "outcome_at": outcome.settled_at.isoformat(),
            "outcome_available_at": labeled["available_at"], "outcome": outcome.payout,
            "probability": forecast.probability, "market_probability": (book.bids[0].price+book.asks[0].price)/2,
            "split": "heldout" if forecast.timestamp >= heldout_start else "train"})
    row_ids = {id(row) for row in rows}
    validation = event_disjoint_validation(rows, training_end=training_end,
        heldout_start=heldout_start, cutoff=as_of, verify_row=lambda row: id(row) in row_ids)
    cohorts = validation["cohorts"]
    # Coverage ranking is not a performance/model-selection claim. Never pool models.
    best = max(cohorts, key=lambda c: (min(c["calibration"]["training_events"], c["calibration"]["heldout_events"]),
        c["calibration"]["training_events"]+c["calibration"]["heldout_events"]), default=None)
    calibration = best["calibration"] if best else {}
    counts["parent_events"] = len({f.event_id for _s, f, _m, _b, _e in originals.values()})
    counts["reviewed_parent_events"] = len(reviewed_parents)
    counts["verified_outcome_forecasts"] = len(labels)
    counts["pending_forecasts"] = len(originals)-len(labels)
    for key in ("studies", "policy_transitions", "withheld_scans", "original_forecasts", "recorded_outcome_matches",
                "source_replayed_forecasts", "pending_forecasts", "verified_outcome_forecasts", "parent_events",
                "reviewed_parent_events"):
        counts.setdefault(key, 0)
    blockers = []
    if not originals:
        blockers.append("no_prospective_independent_forecasts_in_snapshot")
    if not labels:
        blockers.append("no_independently_verified_terminal_outcomes_in_snapshot")
    if calibration.get("training_events", 0) < 100:
        blockers.append("fewer_than_100_independent_training_events")
    if calibration.get("heldout_events", 0) < 100:
        blockers.append("fewer_than_100_independent_heldout_events")
    return {"schema_version": "phase19-qualification-readiness-v1", "evaluated_at": as_of.isoformat(),
        "input_sha256": digest(hashes), "counts": dict(counts), "rejections": dict(rejected),
        "scan_rejections": dict(scan_rejections), "blockers": blockers,
        "scan_rejection_scope": "supplied withheld scans only; multiple reasons per token; not independent opportunities",
        "qualified_training_events": calibration.get("training_events", 0),
        "qualified_heldout_events": calibration.get("heldout_events", 0),
        "qualification_count_scope": "most-complete single homogeneous cohort; cohorts never pooled",
        "selection_policy": "earliest source-replayed forecast per model/reviewed dependency group, selected before labels",
        "cohort_sufficient": any(c["calibration"]["cohort_sufficient"] for c in cohorts),
        "required_training_events": 100, "required_heldout_events": 100,
        "validation": validation, "calibration_rows": rows,
        "execution_economics": {"estimated_net_edge": None, "unprofitable_opportunities": None,
            "reason": "forecast calibration alone cannot verify costs, executable edge or admission"},
        "snapshot_scope": "only supplied original studies; an outcome without its origin cannot qualify",
        "research_only": True, "trading_authority": False, "certification_authority": False,
        "experimental_admission_authority": False}


def replay_event_forecast(study):
    """Recompute the unchanged independent model from original native evidence.

    This proves numerical/model provenance, not provider independence, calibration,
    a frozen training artifact, verified outcomes or trading authority. The rolling
    diffusion model supplies no independently reviewed training cutoff; keep it
    absent rather than inventing a historical freeze time.
    """
    try:
        from neraium_poly.research.phase18.forecasting import forecast_event

        forecast, _market, _book, evidence = _original(study)
        contract = DomainContract.model_validate(study['contract'])
        replayed = forecast_event(contract, tuple(evidence), cutoff=forecast.evidence_cutoff)
        if digest(replayed) != digest(study['model_result']):
            return {'verified': False, 'reason': 'native_input_model_replay_mismatch'}
        return {'verified': True, 'model_training_cutoff': None,
                'scope': 'exact independent model/native-input replay; calibration/freeze/outcome review still required'}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {'verified': False, 'reason': 'independent_forecast_replay_unavailable'}
