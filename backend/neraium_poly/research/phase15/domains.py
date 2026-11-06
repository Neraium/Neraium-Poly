"""Bounded public weather evidence and chronological domain calibration research.

These utilities grant neither experimental admission nor certification authority.
Evidence timestamps record first retrieval, never guessed historical availability.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.finance import digest

NWS_ORIGIN = "https://api.weather.gov"
MAX_BODY = 512 * 1024


def aware(value):
    at = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("aware_timestamp_required")
    return at


async def _nws_get(client, url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.weather.gov" or parsed.query:
        raise ValueError("official_nws_url_required")
    chunks, size = [], 0
    async with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_BODY:
                raise ValueError("bounded_nws_response_required")
            chunks.append(chunk)
    raw = b"".join(chunks)
    return raw, json.loads(raw)


async def collect_nws_precipitation(latitude, longitude, *, client=None, clock=None):
    """Two official GETs: point lookup and its hourly product, no retry loop.

    The point/grid precipitation probability is NOT a station temperature or
    arbitrary rainfall-threshold probability. No market forecast is emitted.
    """
    if (not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float))
            or isinstance(latitude, bool) or isinstance(longitude, bool)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError("finite_coordinates_required")
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, headers={
        "User-Agent": "Neraium-Poly research (https://github.com/Neraium/Neraium-Poly)",
        "Accept": "application/geo+json"})
    clock = clock or (lambda: datetime.now(UTC))
    try:
        lookup = f"{NWS_ORIGIN}/points/{latitude:.4f},{longitude:.4f}"
        point_raw, point = await _nws_get(client, lookup)
        point_at = aware(clock())
        hourly = point["properties"]["forecastHourly"]
        if not urlsplit(hourly).path.endswith("/forecast/hourly"):
            raise ValueError("official_hourly_product_required")
        raw, product = await _nws_get(client, hourly)
        at = aware(clock())
        if at < point_at:
            raise ValueError("retrieval_clock_regression")
        properties = product["properties"]
        issued = aware(properties["updateTime"])
        if issued > at:
            raise ValueError("future_nws_product")
        periods = properties["periods"]
        if not isinstance(periods, list) or len(periods) > 200:
            raise ValueError("bounded_hourly_periods_required")
        qualified = []
        for row in periods:
            start, end = aware(row["startTime"]), aware(row["endTime"])
            pop = row.get("probabilityOfPrecipitation", {})
            value = pop.get("value")
            if end <= start:
                raise ValueError("invalid_nws_period")
            if start <= at or value is None:
                continue
            if pop.get("unitCode") != "wmoUnit:percent" or isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ValueError("qualified_precipitation_percent_required")
            qualified.append({"start": start.isoformat(), "end": end.isoformat(),
                              "provider_probability": value / 100})
        payload = {"source_url": hourly, "point_url": lookup,
            "coordinates": {"latitude": latitude, "longitude": longitude},
            "point_retrieved_at": point_at.isoformat(),
            "raw_point_utf8": point_raw.decode(),
            "raw_point_sha256": hashlib.sha256(point_raw).hexdigest(),
            "raw_response_utf8": raw.decode(), "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
            "periods": qualified, "meaning": "provider point precipitation >=0.01 inch during specified period",
            "station_mapping_verified": False, "market_forecast": False}
        return DomainEvidence(id=digest([payload, at.isoformat()]), timestamp=at, available_at=at,
            source=hourly, domain="weather", provider="NOAA National Weather Service",
            source_id=hourly, retrieved_at=at, source_timestamp=issued,
            content_sha256=digest(payload), payload=payload, independent_of_polymarket=True,
            qualification="qualified_research", missingness=("exact_market_contract_mapping",
                "station_measurement_compatibility", "independent_calibration_cohort"))
    finally:
        if own:
            await client.aclose()


def calibration_report(rows, *, cutoff, verify_raw=None):
    """Score replay-verified independent event forecasts; never promote a model.

    verify_raw(row) must independently replay immutable forecast, external input,
    market baseline, and official outcome evidence. Default is fail closed.
    Exactly one row per dependency group is accepted; later repeats are rejected.
    Split boundaries require ALL train resolutions to precede first held-out
    forecast. Multiple domains/models/features cannot share one calibration report.
    """
    cutoff = aware(cutoff)
    accepted, rejected, groups, bindings = [], Counter(), set(), set()
    dataset = hashlib.sha256()
    for index, row in enumerate(rows):
        if index >= 10000:
            raise ValueError("bounded_calibration_input_required")
        dataset.update(json.dumps(row, sort_keys=True, default=str, allow_nan=True).encode())
        dataset.update(b"\n")
        try:
            times = {key: aware(row[key]) for key in (
                "forecast_at", "evidence_available_at", "market_at", "market_available_at", "outcome_at", "outcome_available_at")}
            if not times["evidence_available_at"] <= times["forecast_at"] < times["outcome_at"] <= times["outcome_available_at"] <= cutoff:
                raise ValueError("noncausal_or_unavailable_evidence")
            if not times["market_at"] <= times["market_available_at"] <= times["forecast_at"] or not 0 <= (times["forecast_at"] - times["market_at"]).total_seconds() <= 60:
                raise ValueError("noncontemporaneous_market_baseline")
            if row.get("uses_market_features") is not False:
                raise ValueError("independent_feature_review_required")
            if not callable(verify_raw) or verify_raw(row) is not True:
                raise ValueError("independent_raw_replay_required")
            group = row["dependency_group"]
            if not isinstance(group, str) or not group:
                raise ValueError("independent_event_group_required")
            if group in groups:
                raise ValueError("repeated_dependency_group")
            p, market, outcome = row["probability"], row["market_probability"], row["outcome"]
            if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or not 0 <= x <= 1 for x in (p, market)) or type(outcome) is not int or outcome not in (0, 1):
                raise ValueError("invalid_binary_scoring_input")
            if row["split"] not in ("train", "heldout"):
                raise ValueError("explicit_chronological_split_required")
            binding = tuple(row[key] for key in ("domain", "model_version", "feature_version", "contract_type"))
            if any(not isinstance(x, str) or not x for x in binding):
                raise ValueError("domain_model_binding_required")
            groups.add(group)
            bindings.add(binding)
            accepted.append({**row, **times})
        except (ValueError, KeyError, TypeError) as exc:
            rejected[str(exc) if isinstance(exc, ValueError) else "missing_calibration_fields"] += 1
    train = [r for r in accepted if r["split"] == "train"]
    heldout = [r for r in accepted if r["split"] == "heldout"]
    blockers = []
    if len(bindings) > 1:
        blockers.append("mixed_domain_model_or_semantics")
    if train and heldout and max(r["outcome_available_at"] for r in train) >= min(r["forecast_at"] for r in heldout):
        blockers.append("chronological_training_leakage")
    if len(train) < 100:
        blockers.append("fewer_than_100_independent_training_events")
    if len(heldout) < 100:
        blockers.append("fewer_than_100_independent_heldout_events")
    metrics = None
    if heldout and not any(x in blockers for x in ("mixed_domain_model_or_semantics", "chronological_training_leakage")):
        def loss(p, y):
            p = min(1 - 1e-12, max(1e-12, p))
            return -y * math.log(p) - (1-y) * math.log1p(-p)
        n = len(heldout)
        deltas = [(r["probability"]-r["outcome"])**2 - (r["market_probability"]-r["outcome"])**2 for r in heldout]
        mean = sum(deltas)/n
        # Distribution-free Hoeffding interval: squared-loss differences in [-1,1].
        radius = math.sqrt(2 * math.log(40)/n)
        metrics = {"brier": sum((r["probability"]-r["outcome"])**2 for r in heldout)/n,
            "market_brier": sum((r["market_probability"]-r["outcome"])**2 for r in heldout)/n,
            "log_loss": sum(loss(r["probability"], r["outcome"]) for r in heldout)/n,
            "market_log_loss": sum(loss(r["market_probability"], r["outcome"]) for r in heldout)/n,
            "brier_difference_95_bound": [max(-1, mean-radius), min(1, mean+radius)],
            "reliability": [{"lower": i/10, "upper": (i+1)/10,
                "count": len(bucket), "mean_forecast": sum(r["probability"] for r in bucket)/len(bucket) if bucket else None,
                "observed_frequency": sum(r["outcome"] for r in bucket)/len(bucket) if bucket else None}
                for i in range(10) for bucket in [[r for r in heldout if min(9, int(r["probability"]*10)) == i]]]}
    return {"dataset_sha256": dataset.hexdigest(), "training_events": len(train), "heldout_events": len(heldout),
        "rejections": dict(rejected), "blockers": blockers, "metrics": metrics,
        "cohort_sufficient": not blockers, "research_only": True,
        "trading_authority": False, "certification_authority": False,
        "execution_cost_adjusted_performance": None,
        "limitations": "Forecast scoring does not verify executable depth, profitability or authorize trading; raw verifier is a required independent trust boundary."}


def qualify_domain_inputs(contract, evidence, *, cutoff):
    """Explain missing exact semantics without creating a fallback probability."""
    cutoff = aware(cutoff)
    reasons = []
    if not contract.compatible or contract.review_required:
        reasons.append("exact_contract_mapping_review_required")
    if not evidence:
        reasons.append("independent_provider_evidence_required")
    for item in evidence:
        if item.domain != contract.domain or not item.independent_of_polymarket or item.qualification != "qualified_research":
            reasons.append("independent_domain_evidence_required")
        if item.available_at > cutoff or item.retrieved_at > cutoff:
            reasons.append("future_or_unavailable_provider_evidence")
        if digest(item.payload) != item.content_sha256:
            reasons.append("evidence_content_hash_mismatch")
        raw = item.payload.get("raw_response_utf8")
        if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != item.payload.get("raw_response_sha256"):
            reasons.append("raw_provider_replay_required")
    if contract.domain == "weather":
        if not contract.parameters.get("station") or not contract.parameters.get("period_start_utc") or not contract.parameters.get("period_end_utc"):
            reasons.append("exact_station_and_observation_window_required")
        elif aware(contract.parameters["period_end_utc"]) <= cutoff:
            reasons.append("observation_window_already_closed")
        reasons.append("station_matched_predictive_distribution_and_calibration_required")
    if contract.domain in ("crypto", "finance"):
        if contract.parameters.get("candle_convention") != "reviewed_minute_ending_boundary":
            reasons.append("explicit_candle_label_vs_close_time_review_required")
        reasons.append("contract_matched_chronological_calibration_required")
    if contract.domain == "economics":
        reasons.append("exact_first_release_vintages_and_calibrated_model_required")
    return {"status": "withheld", "probability": None, "reasons": sorted(set(reasons)),
            "research_only": True, "trading_authority": False, "certification_authority": False}
