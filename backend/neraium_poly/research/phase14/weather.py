"""Exact-rule weather observation research, never deterministic-as-probabilistic.

NOAA/AWC's original METAR text is preserved. Observations describe a partial
station-local day; without a qualified predictive distribution they do not
produce an event probability, settlement, or trading authority.
"""

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence

PROVIDER = "NOAA/NWS Aviation Weather Center"
ORIGIN = "https://aviationweather.gov"
PATH = "/api/data/metar"
MAX_BYTES = 512 * 1024
MAX_ROWS = 400
MODEL_VERSION = "weather-observation-research-v1"
# Full audited RKSI Nov6 2026 rule text, including fallback/correction provisions.
# A similar-looking contract with changed settlement text is not auto-approved.
AUDITED_RULES = "ee971bac629c2bcdd0f492014b5bf6d3908357c3739f0a8ac3314bab91924051"
STATION = {"id": "RKSI", "name": "Incheon Intl Airport", "timezone": "Asia/Seoul",
           "latitude": 37.469, "longitude": 126.451, "units": "Celsius"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware weather timestamp required")
    return value.astimezone(UTC)


def map_weather(market, *, now):
    """Only exact audited RKSI routine-METAR daily-high bins are supported today.

    UTC market closing metadata is retained but is not used as the local weather
    observation boundary. Other stations/variables/rule versions quarantine.
    """
    market = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    now = _aware(now)
    rules_hash = hashlib.sha256(market.resolution_rules.encode()).hexdigest()
    reasons, parameters = [], {}
    if market.timestamp > now or market.available_at > now or market.status != "active":
        reasons.append("weather_noncausal_or_inactive_market")
    if rules_hash != AUDITED_RULES:
        reasons.append("weather_resolution_rule_version_not_reviewed")
    expected_source = ORIGIN + PATH + "?ids=RKSI&format=raw&date=2026-11-06T18:00:00Z&hours=30"
    if market.resolution_source != expected_source:
        reasons.append("weather_exact_station_source_window_required")
    question = re.fullmatch(r"Will the highest temperature in Seoul \(Incheon\) be (-?\d{1,2})°C on November 6\?", market.question)
    if not question or market.outcome not in {"Yes", "No"}:
        reasons.append("weather_unsupported_question_or_outcome")
    if question and not -80 <= int(question.group(1)) <= 60:
        reasons.append("weather_threshold_outside_supported_range")
    if not reasons:
        day = datetime(2026, 11, 6, tzinfo=ZoneInfo(STATION["timezone"]))
        lower = Decimal(question.group(1)) - Decimal("0.5")
        parameters = {
            "market_snapshot": market.model_dump(mode="json"),
            "station": dict(STATION), "variable": "daily_max_routine_metar_temperature",
            "observation_date": day.date().isoformat(), "period_start_utc": day.astimezone(UTC).isoformat(),
            "period_end_utc": (day + timedelta(days=1)).astimezone(UTC).isoformat(),
            "threshold_celsius": int(question.group(1)), "unrounded_lower_inclusive": str(lower),
            "unrounded_upper_exclusive": str(lower + 1), "selected_outcome": market.outcome,
            "rounding": "nearest_integer_half_toward_positive_infinity",
            "temperature_precedence": "raw_T_remark_then_raw_whole_degree_body",
            "routine_definition": "all_reports_except_raw_line_starting_SPECI",
            "source_url": expected_source,
            "source_request_url": ORIGIN + PATH + "?" + urlencode({"ids": "RKSI", "format": "json",
                "date": "2026-11-06T18:00:00Z", "hours": 30}),
            "market_end_metadata": market.end_time.isoformat() if market.end_time else None,
            "corrections_and_fallback": "original_rule_text_governs; no final outcome inferred here",
        }
    return DomainContract(
        id=digest(["weather-contract-v1", market.id, rules_hash]), timestamp=market.timestamp,
        available_at=market.available_at, source=market.source, domain="weather", event_id=market.event_id,
        market_id=market.market_id, token_id=market.token_id,
        contract_type="metar_daily_high_celsius_bin" if not reasons else "unsupported_weather",
        probability_semantics="binary_event_probability" if not reasons else "unsupported",
        rules_sha256=rules_hash, parameters=parameters, compatible=not reasons,
        review_required=bool(reasons), reasons=tuple(reasons),
    )


def _contract(value):
    c = DomainContract.model_validate(value.model_dump() if isinstance(value, DomainContract) else value)
    p = c.parameters
    expected = ORIGIN + PATH + "?" + urlencode({"ids": "RKSI", "format": "json",
                "date": "2026-11-06T18:00:00Z", "hours": 30})
    threshold = p.get("threshold_celsius")
    if (c.probability_semantics != "binary_event_probability" or type(threshold) is not int
        or not -80 <= threshold <= 60 or p.get("selected_outcome") not in {"Yes", "No"}
        or p.get("unrounded_lower_inclusive") != str(Decimal(threshold) - Decimal("0.5"))
        or p.get("unrounded_upper_exclusive") != str(Decimal(threshold) + Decimal("0.5"))
        or c.domain != "weather" or c.contract_type != "metar_daily_high_celsius_bin" or not c.compatible
        or c.review_required or c.reasons or c.rules_sha256 != AUDITED_RULES
        or p.get("station") != STATION or p.get("source_request_url") != expected
        or p.get("observation_date") != "2026-11-06"
        or p.get("period_start_utc") != "2026-11-05T15:00:00+00:00"
        or p.get("period_end_utc") != "2026-11-06T15:00:00+00:00"):
        raise ValueError("qualified exact weather contract required")
    original = MarketSnapshot.model_validate(p.get("market_snapshot", {}))
    if map_weather(original, now=c.available_at) != c:
        raise ValueError("weather contract mapping replay failed")
    return c


def rounded_celsius(value):
    """The contract's negative half example is -8.5 -> -8, not Decimal HALF_UP."""
    return int((Decimal(str(value)) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def _temperature(raw):
    remarks = re.findall(r"(?<!\S)T([01])(\d{3})([01])(\d{3})(?!\S)", raw)
    if len(remarks) > 1:
        raise ValueError("ambiguous_temperature_remarks")
    if remarks:
        sign, number, _dew_sign, _dew_number = remarks[0]
        result, precision = Decimal(number) / 10 * (-1 if sign == "1" else 1), "tenths_Celsius_T_remark"
    else:
        groups = re.findall(r"(?<!\S)(M?\d{2})/(?:M?\d{2}|//)?(?!\S)", raw)
        if len(groups) != 1:
            raise ValueError("missing_or_ambiguous_raw_temperature")
        result = Decimal(groups[0].replace("M", "-"))
        precision = "whole_Celsius_METAR_body"
    if not -100 <= result <= 70:
        raise ValueError("implausible_raw_temperature")
    return float(result), precision


def normalize_metars(raw, contract, *, retrieved_at):
    """Use source observation time, station-local day and original report text.

    This is an as-retrieved source view. It establishes neither historical
    availability before retrieval nor complete final daily settlement evidence.
    """
    c = _contract(contract)
    retrieved_at = _aware(retrieved_at)
    if len(raw) > MAX_BYTES:
        raise ValueError("weather_response_byte_budget")
    rows = json.loads(raw)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("weather_response_row_budget")
    start, end = (datetime.fromisoformat(c.parameters[k]) for k in ("period_start_utc", "period_end_utc"))
    observations, rejected, seen = [], Counter(), {}
    conflicts = set()
    for row in rows:
        try:
            if not isinstance(row, dict) or row.get("icaoId") != STATION["id"]:
                raise ValueError("weather_station_mismatch")
            text = row.get("rawOb")
            if not isinstance(text, str) or len(text) > 4096 or not text.strip():
                raise ValueError("weather_raw_report_missing_or_oversized")
            text = text.strip()
            if text.startswith("SPECI"):
                raise ValueError("special_observation_excluded_by_rules")
            words = text.split()
            index = 1 if words[0] == "METAR" else 0
            if words[index] != STATION["id"]:
                raise ValueError("weather_raw_station_mismatch")
            numeric = row.get("obsTime")
            if isinstance(numeric, bool) or not isinstance(numeric, (int, float)) or not math.isfinite(numeric):
                raise ValueError("weather_observation_timestamp_missing")
            at = datetime.fromtimestamp(numeric, UTC)
            if at > retrieved_at:
                raise ValueError("future_weather_observation")
            if not start <= at < end:
                raise ValueError("outside_station_local_observation_day")
            if words[index + 1] != at.strftime("%d%H%MZ"):
                raise ValueError("raw_and_structured_observation_time_mismatch")
            receipt = datetime.fromisoformat(row["receiptTime"])
            if receipt.tzinfo is None or receipt > retrieved_at or receipt < at:
                raise ValueError("future_or_unverified_provider_receipt_time")
            temperature, precision = _temperature(text)
            key = at.isoformat()
            if key in seen:
                if seen[key] != text:
                    conflicts.add(key)
                    raise ValueError("conflicting_same_observation_revision")
                raise ValueError("duplicate_observation")
            seen[key] = text
            observations.append({"station": STATION["id"], "observation_at": key,
                "provider_receipt_at": receipt.astimezone(UTC).isoformat(), "available_at": retrieved_at.isoformat(),
                "temperature_celsius": temperature, "rounded_celsius": rounded_celsius(temperature),
                "precision": precision, "raw_report": text, "correction": " COR " in " " + text + " "})
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError) as error:
            rejected[str(error)[:100]] += 1
    observations = sorted((o for o in observations if o["observation_at"] not in conflicts),
                          key=lambda o: o["observation_at"])
    return observations, dict(rejected)


async def collect_weather(contract, *, client=None, clock=None):
    """One bounded public GET. 429/5xx withhold; cadence/retry belongs to caller."""
    c = _contract(contract)
    clock = clock or (lambda: datetime.now(UTC))
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=False,
        headers={"User-Agent": "Neraium-Poly/0.1 bounded NOAA weather research"})
    try:
        url = c.parameters["source_request_url"]
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "aviationweather.gov" or parts.path != PATH:
            raise ValueError("weather_source_not_allowed")
        query = parse_qs(parts.query)
        if query.get("ids") != [STATION["id"]] or query.get("format") != ["json"]:
            raise ValueError("weather_source_parameters_changed")
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code == 204:
                return ()
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("weather_redirect_not_allowed")
            if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                raise ValueError("weather_response_byte_budget")
            body = bytearray()
            async for block in response.aiter_bytes():
                body.extend(block)
                if len(body) > MAX_BYTES:
                    raise ValueError("weather_response_byte_budget")
        at = _aware(clock())
        observations, rejected = normalize_metars(bytes(body), c, retrieved_at=at)
        payload = {
            "source_request_url": url, "raw_response_utf8": bytes(body).decode("utf-8"),
            "raw_sha256": hashlib.sha256(body).hexdigest(), "observations": observations,
            "rejected_rows": rejected, "market_id": c.market_id, "event_id": c.event_id,
            "rules_sha256": c.rules_sha256, "station": STATION, "observation_date": c.parameters["observation_date"],
            "maximum_observed_celsius": max((o["temperature_celsius"] for o in observations), default=None),
            "observation_period_complete": False,
            "full_resolution_evidence": False, "source_product": "observations_not_probabilistic_forecast",
            "original_contract": c.model_dump(mode="json"),
        }
        stamp = max((datetime.fromisoformat(o["observation_at"]) for o in observations), default=at)
        record = DomainEvidence(id=digest(["awc-metar-v1", payload, at.isoformat()]), timestamp=stamp,
            available_at=at, source=url, domain="weather", provider=PROVIDER, source_id="RKSI/METAR/2026-11-06",
            retrieved_at=at, source_timestamp=max((datetime.fromisoformat(o["provider_receipt_at"]) for o in observations), default=None),
            content_sha256=digest(payload),
            payload=payload, independent_of_polymarket=True,
            qualification="qualified_research" if observations else "unqualified",
            missingness=("complete_final_station_local_day", "qualified_station_predictive_distribution",
                         "heldout_calibration", "independent_final_outcome_verification"))
        return (record,)
    finally:
        if own:
            await client.aclose()


def forecast_weather(contract, evidence, *, cutoff):
    """Withhold probability: observed/deterministic temperature is not a distribution."""
    c = _contract(contract)
    cutoff = _aware(cutoff)
    reasons, observed = [], set()
    if c.available_at > cutoff:
        reasons.append("weather_contract_not_available_at_cutoff")
    for index, value in enumerate(evidence):
        if index >= 8:
            reasons.append("weather_evidence_record_budget")
            break
        e = DomainEvidence.model_validate(value.model_dump() if isinstance(value, DomainEvidence) else value)
        if (e.domain != "weather" or e.provider != PROVIDER or e.source != c.parameters["source_request_url"]
            or e.payload.get("source_request_url") != e.source
            or e.payload.get("original_contract") != c.model_dump(mode="json")
            or e.source_id != "RKSI/METAR/2026-11-06" or e.available_at > cutoff or e.timestamp > cutoff
            or not e.independent_of_polymarket or e.qualification != "qualified_research"
            or digest(e.payload) != e.content_sha256 or e.payload.get("rules_sha256") != c.rules_sha256
            or e.payload.get("market_id") != c.market_id or e.payload.get("event_id") != c.event_id):
            reasons.append("noncausal_or_mismatched_weather_evidence")
            continue
        text = e.payload.get("raw_response_utf8")
        if not isinstance(text, str) or len(text) > MAX_BYTES:
            reasons.append("missing_or_oversized_weather_source_bytes")
            continue
        body = text.encode()
        if hashlib.sha256(body).hexdigest() != e.payload.get("raw_sha256"):
            reasons.append("corrupt_weather_source_bytes")
            continue
        try:
            replay, rejected = normalize_metars(body, c, retrieved_at=e.retrieved_at)
        except (ValueError, TypeError):
            reasons.append("weather_source_normalization_replay_failed")
            continue
        if replay != e.payload.get("observations") or rejected != e.payload.get("rejected_rows"):
            reasons.append("weather_source_normalization_replay_failed")
            continue
        observed.update((o["station"], o["observation_at"], o["raw_report"]) for o in replay)
    reasons.append("qualified_station_matched_predictive_distribution_and_calibration_required")
    if not observed:
        reasons.append("qualified_weather_observations_missing")
    return {"domain": "weather", "model_version": MODEL_VERSION, "qualified": False,
            "probability": None, "uncertainty": None, "calibration_status": "unavailable",
            "support_status": "observation_research_only", "qualified_observations": len(observed),
            "reasons": sorted(set(reasons)), "forecast_recorded": False,
            "trading_authority": False, "certification_authority": False}


class WeatherObservationModel:
    domain = "weather"
    model_version = MODEL_VERSION
    supported_contract_types = ("metar_daily_high_celsius_bin",)

    def forecast(self, contract, evidence, *, cutoff):
        return forecast_weather(contract, evidence, cutoff=cutoff)
