"""Prospective, paired SII ablations; never a source of trading authority.

No SII probability is synthesized. A separately frozen challenger and independently
replayed, persistent causal relationship inputs are required. Existing native
forecast/outcome contracts authenticate the supplied original studies.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from math import isfinite, log, sqrt

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase19.qualification import _label, _original

VERSION = "phase20-paired-sii-v1"
AUTHORITY = {"research_only": True, "trading_authority": False, "certification_authority": False,
             "experimental_admission_authority": False}


def _at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_ab_time_required")
    return value.astimezone(UTC)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _prob(value):
    return type(value) in (int, float) and isfinite(value) and 0 <= value <= 1


def _check(callback, *values):
    if not callable(callback):
        return None
    try:
        return callback(*deepcopy(values))
    except Exception:  # noqa: BLE001 - unavailable replay must never create a paired prediction
        return None


def declare_experiment(*, experiment_id, declared_at, heldout_start, baseline_model_sha256,
                       challenger_model_sha256=None, challenger_feature_version=None,
                       training_groups=(), execution_assumptions=None):
    """Freeze before prospective enrollment; missing challenger remains untestable.

    This manifest records research intent, not model/source approval. All times
    are actual declaration/availability times; retrospective pre-registration is
    invalid. Its hash must be committed to the existing append-only archive.
    """
    declared_at, heldout_start = map(_at, (declared_at, heldout_start))
    if not declared_at <= heldout_start:
        raise ValueError("predeclared_chronological_ab_boundary_required")
    if not isinstance(experiment_id, str) or not 1 <= len(experiment_id) <= 128 or not _sha(baseline_model_sha256):
        raise ValueError("bounded_ab_identity_and_baseline_hash_required")
    if challenger_model_sha256 is not None and not _sha(challenger_model_sha256):
        raise ValueError("valid_frozen_challenger_hash_required")
    if challenger_model_sha256 and (not isinstance(challenger_feature_version, str)
                                   or not 1 <= len(challenger_feature_version) <= 128):
        raise ValueError("frozen_challenger_feature_version_required")
    if (not isinstance(training_groups, (list, tuple)) or len(training_groups) > 10000
        or any(not isinstance(g, str) or not 1 <= len(g) <= 256 for g in training_groups)):
        raise ValueError("bounded_predeclared_training_groups_required")
    assumptions = deepcopy(execution_assumptions or {})
    if not isinstance(assumptions, dict) or len(str(assumptions)) > 8192:
        raise ValueError("bounded_shared_execution_assumptions_required")
    spec = {"schema_version": VERSION, "experiment_id": experiment_id,
            "declared_at": declared_at.isoformat(), "heldout_start": heldout_start.isoformat(),
            "baseline_model_sha256": baseline_model_sha256,
            "challenger_model_sha256": challenger_model_sha256,
            "challenger_feature_version": challenger_feature_version,
            "training_groups": sorted(set(training_groups)), "execution_assumptions": assumptions,
            "event_selection": "earliest_eligible_pair_per_reviewed_dependency_group",
            "uncertainty_method": "paired_group_hoeffding_95_simultaneous_two_comparisons",
            "outcome_target": "verified_binary_terminal_event", **AUTHORITY}
    return {**spec, "manifest_sha256": digest(spec)}


def _spec(experiment):
    raw = deepcopy(experiment)
    sha = raw.pop("manifest_sha256", None)
    if raw.get("schema_version") != VERSION or digest(raw) != sha:
        raise ValueError("ab_manifest_integrity_required")
    rebuilt = declare_experiment(**{k: raw[k] for k in (
        "experiment_id", "declared_at", "heldout_start", "baseline_model_sha256",
        "challenger_model_sha256", "challenger_feature_version", "training_groups", "execution_assumptions")})
    if rebuilt != experiment:
        raise ValueError("unsupported_ab_policy_or_authority")
    return rebuilt


def _features(features, *, cutoff, verify_features):
    if not isinstance(features, dict):
        raise ValueError("persistent_replayed_sii_features_unavailable")  # noqa: TRY004 - missing capability
    # Native UniversalRelationships results retain exact evidence and baseline lineage.
    if (features.get("engine_version") != "universal-joint-relationship-v1"
        or not _sha(features.get("engine_sha256")) or features.get("persistent") is not True
        or features.get("classification") not in {"persistent_statistical_relationship_change",
                                                "reviewed_logical_constraint_violation"}
        or type(features.get("persistence_count")) is not int or features["persistence_count"] < 3):
        raise ValueError("qualified_persistent_sii_relationship_required")
    times = [_at(features[k]) for k in ("baseline_cutoff", "persistence_since", "evaluated_at", "available_at")]
    if not times[0] <= times[1] <= times[2] <= times[3] <= cutoff or (times[2]-times[1]).total_seconds() < 60:
        raise ValueError("causal_sii_baseline_persistence_and_availability_required")
    if not _sha(features.get("definition_sha256")) or not features.get("uncertainty"):
        raise ValueError("sii_definition_and_uncertainty_required")
    for key, minimum in (("evidence_sha256", 2), ("baseline_evidence_sha256", 10),
                         ("current_window_evidence_sha256", 3)):
        hashes = features.get(key)
        if (not isinstance(hashes, list) or not minimum <= len(hashes) <= 100
            or len(set(hashes)) != len(hashes) or any(not _sha(h) for h in hashes)):
            raise ValueError("distinct_causal_sii_lineage_required")
    replay = _check(verify_features, features)
    if (not isinstance(replay, dict) or replay.get("verified") is not True
        or type(replay.get("uses_market_features")) is not bool):
        raise ValueError("independent_sii_raw_lineage_replay_required")
    return replay


def prospective_pair(study, *, experiment, now, sii_features=None, challenger=None,
                     verify_forecast=None, verify_features=None, verify_challenger=None):
    """Prepare one immutable envelope for the existing evidence archive.

    Call at actual forecast-generation time. Replaying an old forecast after its
    event closes cannot manufacture a prospective comparison. Missing challenger
    artifacts are recorded as withheld, not an identical or invented SII arm.
    """
    spec, now = _spec(experiment), _at(now)
    reasons, pair, enrollment = [], None, None
    try:
        f, m, b, _ = _original(study)
        if (not _at(spec["declared_at"]) <= _at(spec["heldout_start"]) <= f.timestamp <= now < m.end_time
            or f.available_at > now or _at(study["available_at"]) > now):
            raise ValueError("prospective_predeclared_event_enrollment_required")
        if f.model_sha256 != spec["baseline_model_sha256"]:
            raise ValueError("predeclared_baseline_model_mismatch")
        enrollment = {"forecast_id": f.id, "event_id": f.event_id, "market_id": f.market_id,
                      "token_id": f.token_id, "forecast_at": f.timestamp.isoformat(),
                      "evidence_cutoff": f.evidence_cutoff.isoformat(), "forecast_sha256": digest(study["forecast"]),
                      "book_sha256": digest(study["book"]), "rules_sha256": f.rules_sha256,
                      "evidence_sha256": [e.content_sha256 for e in _],
                      "baseline_probability": f.probability,
                      "market_probability": (b.bids[0].price+b.asks[0].price)/2}
        replay = _check(verify_forecast, study)
        if not isinstance(replay, dict) or replay.get("verified") is not True:
            raise ValueError("original_independent_forecast_replay_required")
        if not spec["challenger_model_sha256"]:
            raise ValueError("frozen_trained_sii_challenger_unavailable")
        lineage = _features(sii_features, cutoff=f.evidence_cutoff, verify_features=verify_features)
        if not isinstance(challenger, dict):
            raise ValueError("frozen_challenger_prediction_unavailable")  # noqa: TRY004 - absent artifact
        expected = {"experiment_sha256": spec["manifest_sha256"], "forecast_sha256": digest(study["forecast"]),
                    "features_sha256": digest(sii_features), "model_sha256": spec["challenger_model_sha256"],
                    "feature_version": spec["challenger_feature_version"],
                    "event_id": f.event_id, "market_id": f.market_id, "token_id": f.token_id,
                    "rules_sha256": f.rules_sha256}
        if (any(challenger.get(k) != v for k, v in expected.items()) or not _prob(challenger.get("probability"))
            or _at(challenger["timestamp"]) != f.timestamp or _at(challenger["evidence_cutoff"]) != f.evidence_cutoff):
            raise ValueError("same_cutoff_event_rule_and_frozen_challenger_binding_required")
        if not (_at(challenger["trained_at"]) <= _at(spec["declared_at"])
                and _at(challenger["available_at"]) <= now):
            raise ValueError("predeclared_frozen_challenger_artifact_required")
        if _check(verify_challenger, challenger, study, sii_features) is not True:
            raise ValueError("independent_frozen_challenger_replay_required")
        pair = {"forecast_id": f.id, "event_id": f.event_id, "market_id": f.market_id, "token_id": f.token_id,
                "forecast_at": f.timestamp.isoformat(), "evidence_cutoff": f.evidence_cutoff.isoformat(),
                "baseline_probability": f.probability, "sii_probability": challenger["probability"],
                "market_probability": (b.bids[0].price+b.asks[0].price)/2,
                "original_study_sha256": digest(study), "book_sha256": digest(study["book"]),
                "sii_features_sha256": digest(sii_features), "challenger_sha256": digest(challenger),
                "baseline_independent_of_market": True,
                "sii_independent_of_market": not lineage["uses_market_features"]}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        reasons.append(str(exc)[:160] if isinstance(exc, ValueError) else "malformed_ab_input")
    result = {"schema_version": VERSION, "operation": "prospective_sii_pair", "recorded_at": now.isoformat(),
              "experiment_sha256": spec["manifest_sha256"], "original_study_sha256": digest(study),
              "status": "paired_research" if pair else "withheld", "pair": pair, "enrollment": enrollment, "reasons": reasons,
              "after_cost_edge": None, "simulated_pnl": None,
              "economics_reason": "paired_forecasting_skill_is_not_executable_edge", **AUTHORITY}
    return {**result, "record_sha256": digest(result)}


def _loss(p, y):
    likelihood = p if y else 1-p
    return None if likelihood == 0 else -log(likelihood)


def _scores(rows, key):
    losses = [_loss(r[key], r["outcome"]) for r in rows]
    return {"brier": sum((r[key]-r["outcome"])**2 for r in rows)/len(rows),
            "log_loss": None if any(x is None for x in losses) else sum(losses)/len(rows),
            "log_loss_status": "positive_infinity" if any(x is None for x in losses) else "finite",
            "reliability": [{"lower": i/10, "upper": (i+1)/10,
                "count": len(bucket), "mean_probability": sum(r[key] for r in bucket)/len(bucket) if bucket else None,
                "observed_frequency": sum(r["outcome"] for r in bucket)/len(bucket) if bucket else None}
                for i in range(10) for bucket in [[r for r in rows if min(9, int(r[key]*10)) == i]]]}


def evaluate_pairs(pairs, originals, outcome_studies, *, experiment, as_of,
                   verify_pair=None, verify_forecast=None, verify_outcome=None, review_group=None):
    """Equal-weight, earliest-pair-per-independent-group held-out evaluation.

    All replay callbacks default deny. Independent binary outcome verification is
    distinct from evaluating a forecast. The bound covers two predeclared Brier
    comparisons simultaneously; it does not adjust for unreported experiments.
    """
    spec, as_of = _spec(experiment), _at(as_of)
    if any(not isinstance(x, (list, tuple)) or len(x) > 4096 for x in (pairs, originals, outcome_studies)):
        raise ValueError("bounded_ab_snapshot_required")
    if sum(len(str(x)) for x in (pairs, originals, outcome_studies)) > 128*1024**2:
        raise ValueError("bounded_ab_snapshot_bytes_required")
    origins, labels = {}, defaultdict(list)
    conflicts, rejected, withheld = set(), Counter(), Counter()
    for s in originals:
        if not isinstance(s, dict) or not isinstance(s.get("forecast"), dict):
            continue
        fid = s["forecast"].get("id")
        if fid in origins and digest(origins[fid]) != digest(s):
            conflicts.add(fid)
        origins[fid] = s
    for s in outcome_studies:
        if isinstance(s, dict) and isinstance(s.get("forecast"), dict):
            labels[s["forecast"].get("id")].append(s)
    selected, parent_groups, seen = [], defaultdict(set), set()
    for envelope in pairs:
        try:
            if not isinstance(envelope, dict):
                raise TypeError("structured_ab_pair_required")
            original_envelope = deepcopy(envelope)
            claimed = original_envelope.pop("record_sha256", None)
            if digest(original_envelope) != claimed or envelope.get("experiment_sha256") != spec["manifest_sha256"]:
                raise ValueError("paired_record_or_experiment_integrity_required")
            if claimed in seen:
                rejected["duplicate_pair_record"] += 1
                continue
            seen.add(claimed)
            if envelope.get("status") == "withheld":
                withheld.update(envelope.get("reasons", ["withheld_pair"]))
                continue
            if _at(envelope["recorded_at"]) > as_of or _check(verify_pair, envelope) is not True:
                raise ValueError("independent_prospective_pair_replay_required")
            p = envelope["pair"]
            if not all(_prob(p.get(k)) for k in ("baseline_probability", "sii_probability", "market_probability")):
                raise ValueError("valid_paired_probabilities_required")
            if p["forecast_id"] in conflicts:
                raise ValueError("conflicting_original_forecast_id")
            origin = origins[p["forecast_id"]]
            f, market, book, _ = _original(origin)
            if p["original_study_sha256"] != digest(origin) or p["book_sha256"] != digest(origin["book"]):
                raise ValueError("paired_original_context_binding_required")
            if (f.model_sha256 != spec["baseline_model_sha256"] or p["baseline_probability"] != f.probability
                or p["market_probability"] != (book.bids[0].price+book.asks[0].price)/2
                or (p["event_id"], p["market_id"], p["token_id"]) != (f.event_id, f.market_id, f.token_id)
                or p["forecast_at"] != f.timestamp.isoformat() or p["evidence_cutoff"] != f.evidence_cutoff.isoformat()
                or not _at(spec["heldout_start"]) <= f.timestamp <= _at(envelope["recorded_at"]) < market.end_time):
                raise ValueError("same_prospective_cutoff_original_event_required")
            replay = _check(verify_forecast, origin)
            if not isinstance(replay, dict) or replay.get("verified") is not True:
                raise ValueError("independent_baseline_source_replay_required")
            reviewed = _check(review_group, origin)
            if (not isinstance(reviewed, dict) or reviewed.get("reviewed") is not True
                or not isinstance(reviewed.get("dependency_group"), str) or not reviewed["dependency_group"]):
                raise ValueError("reviewed_independent_event_group_required")
            group = reviewed["dependency_group"]
            parent_groups[f.event_id].add(group)
            if group in spec["training_groups"]:
                raise ValueError("heldout_event_group_in_training")
            selected.append({**deepcopy(p), "dependency_group": group,
                             "record_sha256": claimed})
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected[str(exc)[:160] if isinstance(exc, ValueError) else "malformed_ab_evaluation_row"] += 1
    ambiguous = {p for p, gs in parent_groups.items() if len(gs) != 1}
    by_group = {}
    for p in sorted(selected, key=lambda p: (p["forecast_at"], p["forecast_id"], p["record_sha256"])):
        if p["event_id"] in ambiguous:
            rejected["inconsistent_parent_dependency_group"] += 1
        elif p["dependency_group"] in by_group:
            rejected["repeated_dependency_group_not_independent"] += 1
        else:
            by_group[p["dependency_group"]] = p
    # Choose the earliest eligible forecast BEFORE looking at any outcome. A
    # later resolved update must not replace an unresolved/loss-making origin.
    rows = []
    for p in by_group.values():
        try:
            origin = origins[p["forecast_id"]]
            f, market, _book, _evidence = _original(origin)
            eligible, payouts = [], set()
            for s in labels[f.id]:
                outcome = _label(s, origin, f, market, as_of)
                payouts.add(outcome.payout)
                if _check(verify_outcome, s, origin) is True:
                    eligible.append(outcome)
            if len(payouts) > 1:
                raise ValueError("conflicting_outcomes_preserve_unresolved")
            if not eligible:
                raise ValueError("independently_verified_terminal_outcome_pending")
            rows.append({**p, "outcome": eligible[0].payout})
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected[str(exc)[:160] if isinstance(exc, ValueError) else "malformed_ab_outcome_row"] += 1
    metrics = None
    if rows:
        n, radius = len(rows), sqrt(2*log(80)/len(rows))
        deltas = {"sii_minus_baseline": [(r["sii_probability"]-r["outcome"])**2
                                         -(r["baseline_probability"]-r["outcome"])**2 for r in rows],
                  "sii_minus_market": [(r["sii_probability"]-r["outcome"])**2
                                       -(r["market_probability"]-r["outcome"])**2 for r in rows]}
        comparisons = {}
        for name, values in deltas.items():
            delta = sum(values)/n
            interval = [max(-1., delta-radius), min(1., delta+radius)]
            comparisons[name] = {"paired_brier_difference": delta, "simultaneous_95_bound": interval,
                                 "superiority_supported": interval[1] < 0}
        metrics = {"baseline": _scores(rows, "baseline_probability"), "with_sii": _scores(rows, "sii_probability"),
                   "market": _scores(rows, "market_probability"), "comparisons": comparisons,
                   "sample_unit": "one earliest prospective pair per independently reviewed dependency group",
                   "independent_groups": n, "confidence_method": spec["uncertainty_method"]}
    return {"schema_version": VERSION, "experiment_sha256": spec["manifest_sha256"],
            "evaluated_at": as_of.isoformat(), "paired_records": len(pairs), "verified_independent_groups": len(rows),
            "withheld_reasons": dict(withheld), "rejections": dict(rejected), "ambiguous_parents": sorted(ambiguous),
            "metrics": metrics, "scored_pair_ids": [r["record_sha256"] for r in rows],
            "incremental_sii_skill_supported": bool(metrics and metrics["comparisons"]["sii_minus_baseline"]["superiority_supported"]),
            "after_cost_edge": None, "simulated_returns": None, "risk_adjusted_returns": None,
            "execution_reason": "forecast_scores_do_not_establish_costs_fills_lockup_or_trading_advantage",
            "required_certified_training_events": 100, "required_certified_heldout_events": 100,
            "limitations": ["Reviewed groups must actually be independent for the confidence bound",
                            "Exploratory repeated testing and unreported model searches invalidate confirmatory claims",
                            "Market-derived SII features make the augmented model market-informed"], **AUTHORITY}
