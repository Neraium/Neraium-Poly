"""Source-replayed event identity review, distinct from statistical independence."""

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from neraium_poly.research.phase14.relationships import digest

AUTHORITY = {"research_only": True, "trading_authority": False, "certification_authority": False}
VERSION = "phase25-source-event-review-v1"


def at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_event_review_time_required")
    return value.astimezone(UTC)


def text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError("bounded_exact_event_identity_required")
    return value


def _source(value):
    value = text(value)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("exact_https_resolution_reference_required")
    return value


def bound_forecasts(studies, *, as_of):
    """Keep original records and quarantine every conflicting forecast identity."""
    now = at(as_of)
    if not isinstance(studies, (tuple, list)) or len(studies) > 2000:
        raise ValueError("bounded_event_review_studies_required")
    found, conflicts, reasons = {}, set(), Counter()
    total = 0
    for study in studies:
        for forecast in study.get("forecasts", []):
            total += 1
            if total > 10000:
                raise ValueError("bounded_event_review_forecasts_required")
            try:
                identity = text(forecast["id"])
                if not (at(forecast["evidence_cutoff"]) <= at(forecast["timestamp"])
                        <= at(study["available_at"]) <= now
                        and at(study["available_at"]) < at(forecast["event_end_time"])):
                    raise ValueError("durable_prospective_event_observation_required")
                if (forecast.get("research_only") is not True
                        or forecast.get("trading_authority") is not False
                        or forecast.get("certification_authority") is not False):
                    raise ValueError("research_only_event_review_required")
                market = forecast["market"]
                if (any(market[k] != forecast[k] for k in ("event_id", "market_id", "token_id"))
                        or hashlib.sha256(market["resolution_rules"].encode()).hexdigest() != forecast["rules_sha256"]
                        or at(market["available_at"]) > at(forecast["evidence_cutoff"])):
                    raise ValueError("exact_native_market_rules_identity_required")
                value = {"study": study, "forecast": forecast}
                if identity in conflicts:
                    continue
                old = found.get(identity)
                if old and digest(old["forecast"]) != digest(forecast):
                    found.pop(identity)
                    conflicts.add(identity)
                    raise ValueError("conflicting_original_forecast_identity")
                if old is None or at(study["available_at"]) < at(old["study"]["available_at"]):
                    found[identity] = value
            except (ValueError, KeyError, TypeError, OverflowError, OSError, StopIteration) as error:
                reasons[str(error)[:120]] += 1
    return found, reasons


def canonical_event(forecast):
    """Use mapped source identities only; never derive participants from keywords."""
    f = forecast
    domain = text(f["domain"])
    contract = f.get("contract", {})
    params = contract.get("parameters", contract)
    reference = _source(f["market"]["resolution_source"])
    descriptor = {"domain": domain, "resolution_reference": reference}
    if domain == "sports":
        mapping = f.get("sports_mapping")
        if mapping:
            league = text(mapping["league"])
            participants = sorted([text(mapping["selected_team_id"]), text(mapping["opponent_team_id"])])
            start, game = at(mapping["event_start"]), text(mapping["game_id"])
            provider = text(mapping["provider"])
        else:
            league = text(f["league"])
            participants = sorted(text(p) for p in params["participants"])
            start, game = at(params["scheduled_start"]), text(f["source_game_id"])
            provider = ";".join(sorted(text(p) for p in f["source_lineages"]))
        if len(participants) != 2 or len(set(participants)) != 2 or start != at(f["event_end_time"]):
            raise ValueError("exact_two_participant_source_game_required")
        descriptor.update(league=league, participants=participants, starts_at=start.isoformat(),
                          source_game_id=game, source_id_namespace=provider + ":" + league)
        key = [domain, league, participants, start.isoformat()]
        tags = [f"team:{league}:{p}" for p in participants]
    elif domain == "weather":
        station, day = text(params["station"]), text(params["day"])
        start, end = at(params["period_start"]), at(params["period_end"])
        zone = ZoneInfo(text(params["timezone"]))
        if not 23 * 3600 <= (end - start).total_seconds() <= 25 * 3600 or start.astimezone(zone).date().isoformat() != day:
            raise ValueError("exact_station_local_observation_window_required")
        variable = text(params.get("variable", "daily_high_temperature"))
        descriptor.update(station=station, day=day, variable=variable, starts_at=start.isoformat(), ends_at=end.isoformat())
        key = [domain, station, variable, start.isoformat(), end.isoformat()]
        tags = ["weather-station:" + station, "weather-UTC-day:" + start.date().isoformat()]
    elif domain == "crypto":
        symbol = text(params["symbol"])
        start, end = at(params["period_start_utc"]), at(params["period_end_utc"])
        if start >= end or end != at(f["event_end_time"]):
            raise ValueError("exact_crypto_reference_window_required")
        descriptor.update(symbol=symbol, starts_at=start.isoformat(), ends_at=end.isoformat())
        key = [domain, symbol, reference, start.isoformat(), end.isoformat()]
        tags = ["crypto-symbol:" + symbol, "crypto-UTC-day:" + start.date().isoformat()]
    elif domain == "economics":
        if params.get("kind") == "fomc":
            series, period = "FED:scheduled-FOMC", text(params["meeting_date"])
        else:
            series, period = text(params["series_id"]), text(params["target_period"])
        descriptor.update(series_id=series, target_period=period)
        key = [domain, series, period]
        tags = ["economic-series:" + series]
    elif domain == "finance":
        symbol, source = text(params["symbol"]), _source(params["reference_source"])
        start, end = at(params["period_start"]), at(params["period_end"])
        if start >= end or end != at(params["settlement_at"]):
            raise ValueError("exact_financial_reference_session_required")
        descriptor.update(symbol=symbol, starts_at=start.isoformat(), ends_at=end.isoformat(), reference_source=source)
        key = [domain, symbol, source, start.isoformat(), end.isoformat()]
        tags = ["financial-symbol:" + symbol, "financial-UTC-day:" + end.date().isoformat()]
    else:
        raise ValueError("reviewed_domain_event_mapping_unavailable")
    return descriptor, digest([VERSION, key]), tags


def review_events(studies, *, as_of, forecast_verifier=None):
    """Review canonical identity with explicit provenance, never certify independence.

    The caller must independently authenticate the original source/model via
    forecast_verifier(study, forecast, as_of=UTC_datetime). A verified flag stored
    in a forecast is never sufficient. Risk clusters are conservative shared
    participant/series/day controls, not measured causal or correlation findings.
    """
    now = at(as_of)
    found, reasons = bound_forecasts(studies, as_of=now)
    reviews, candidates, conflicts = [], {}, set()
    for identity, value in sorted(found.items()):
        study, f = value["study"], value["forecast"]
        try:
            if not callable(forecast_verifier):
                raise TypeError("independently_replayed_source_model_required")
            proof = forecast_verifier(study, f, as_of=now)
            if not isinstance(proof, dict) or proof.get("verified") is not True:
                raise TypeError("independently_replayed_source_model_required")
            descriptor, group, tags = canonical_event(f)
            row = {"forecast_id": identity, "model_id": f.get("model_id", f.get("model_version")),
                   "native_parent_id": f["event_id"], "canonical_group_id": group, "descriptor": descriptor,
                   "dependency_tags": tags, "evidence_lineages": sorted(set(f.get("source_lineages", []))),
                   "original_study_id": study["id"], "original_study_sha256": digest(study),
                   "original_forecast_sha256": digest(f), "source_model_replay_verified": True,
                   "review_policy": VERSION, "review_status": "source_event_identity_reviewed",
                   "statistical_independence_established": False, "certified_group_id": None, **AUTHORITY}
            if descriptor.get("source_game_id"):
                key = (descriptor["source_id_namespace"], descriptor["source_game_id"])
                if key in candidates and candidates[key] != group:
                    conflicts.add(key)
                candidates[key] = group
            reviews.append(row)
        except (ValueError, KeyError, TypeError, OverflowError, OSError, StopIteration) as error:
            reasons[str(error)[:120]] += 1
    if conflicts:
        reviews = [r for r in reviews if (r["descriptor"].get("source_id_namespace"), r["descriptor"].get("source_game_id")) not in conflicts]
        reasons["conflicting_source_game_identity"] += len(conflicts)
    groups, lineages, tag_groups = defaultdict(list), defaultdict(set), defaultdict(set)
    for row in reviews:
        group = row["canonical_group_id"]
        groups[group].append(row)
        for tag in row["dependency_tags"]:
            tag_groups[tag].add(group)
        for lineage in row["evidence_lineages"]:
            lineages[lineage].add(group)
    parent = {group: group for group in groups}
    def root(group):
        while parent[group] != group:
            parent[group] = parent[parent[group]]
            group = parent[group]
        return group
    for values in tag_groups.values():
        ordered = sorted(values)
        for group in ordered[1:]:
            a, b = root(ordered[0]), root(group)
            if a != b:
                parent[max(a, b)] = min(a, b)
    clusters = defaultdict(list)
    for group in sorted(groups):
        clusters[root(group)].append(group)
    return {"schema_version": VERSION, "as_of": now.isoformat(), "reviews": reviews,
            "counts": {"forecasts_examined": len(found), "source_identity_reviewed_forecasts": len(reviews),
                       "native_parent_ids": len({v["forecast"]["event_id"] for v in found.values()}),
                       "reviewed_canonical_groups": len(groups), "conservative_dependency_clusters": len(clusters),
                       "statistically_independent_events": 0, "certification_independent_events": 0},
            "groups": [{"canonical_group_id": group, "forecasts": len(rows),
                        "native_parent_ids": sorted({r["native_parent_id"] for r in rows}),
                        "models": sorted({r["model_id"] for r in rows})} for group, rows in sorted(groups.items())],
            "dependency_clusters": [sorted(values) for _, values in sorted(clusters.items())],
            "shared_evidence_lineages": [{"lineage": lineage, "canonical_groups": sorted(values)}
                                         for lineage, values in sorted(lineages.items()) if len(values) > 1],
            "rejections": dict(reasons), "certification_requirements": {"training": 100, "heldout": 100},
            "limitations": ["Canonical events are identity-reviewed, not certified statistically independent samples",
                            "Shared teams/stations/assets/release series and contemporaneous regimes remain dependent",
                            "A shared publisher or model input is not independent supporting confirmation"], **AUTHORITY}
