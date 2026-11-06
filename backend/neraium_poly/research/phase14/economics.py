"""Official economic context and release-vintage qualification, not invented consensus."""
import hashlib
import math
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.finance import _read, digest

FOMC_CALENDAR = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
OFFICIAL_HOSTS = {"www.federalreserve.gov", "www.bls.gov", "www.bea.gov", "api.stlouisfed.org", "fred.stlouisfed.org"}


def map_economic(market, *, now):
    m = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    if now.tzinfo is None or m.available_at > now or m.timestamp > now or m.status != "active":
        raise ValueError("economic_noncausal_or_inactive_market")
    host = urlsplit(m.resolution_source).hostname
    official = host in OFFICIAL_HOSTS
    upper_bound = official and "upper bound of the target federal funds" in m.resolution_rules
    return DomainContract(id=digest([m.id, "economic-contract-v1"]), timestamp=now, available_at=now,
        source="neraium-poly/economic-contract/v1", domain="economics", event_id=m.event_id,
        market_id=m.market_id, token_id=m.token_id, contract_type="fomc_target_upper_bound_change" if upper_bound else "economic_release_review",
        probability_semantics="unsupported", rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
        parameters={"resolution_source": m.resolution_source, "reference_variable": "target_federal_funds_upper_bound" if upper_bound else None,
                    "calendar_url": FOMC_CALENDAR if upper_bound else None,
                    "effective_funds_rate_is_not_target_upper_bound": upper_bound,
                    "preliminary_vs_revised": "unqualified_until_exact_release_vintage_verified"},
        compatible=False, review_required=True,
        reasons=("release_vintage_and_exact_settlement_definition_review_required", "independent_economic_model_not_validated"))


async def collect_economic(contract, *, client=None, clock=None):
    """Collect the official FOMC calendar as context; publication time is unknown."""
    c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
    if c.domain != "economics" or c.parameters.get("calendar_url") != FOMC_CALENDAR:
        raise ValueError("economic_supported_official_context_required")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers={"User-Agent": "Neraium-Poly public research/0.1"})
    clock = clock or (lambda: datetime.now(UTC))
    try:
        raw = await _read(client, FOMC_CALENDAR)
        at = clock()
        body = raw.decode("utf-8")
        if "FOMC" not in body or "federalreserve" not in body.lower():
            raise ValueError("economic_calendar_source_schema")
        payload = {"source_url": FOMC_CALENDAR, "raw_response_utf8": body,
                   "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
                   "meaning": "Current official meeting calendar context, not release outcome or market consensus",
                   "historic_vintage": False}
        return (DomainEvidence(id=digest(["fomc-calendar", payload, at.isoformat()]), timestamp=at,
            available_at=at, source=FOMC_CALENDAR, domain="economics", provider="Board of Governors of the Federal Reserve System",
            source_id="fomc-calendar-current", retrieved_at=at, content_sha256=digest(payload), payload=payload,
            independent_of_polymarket=True, qualification="qualified_research",
            missingness=("exact_publication_time", "historical_vintages", "qualified_consensus", "calibrated_economic_probability_model")),)
    finally:
        if own:
            await client.aclose()


def qualify_economic_vintages(observations, *, cutoff):
    """Accept only explicit first-release facts actually observed before cutoff.

    Observation date is never used as publication date. FRED latest/revised values
    without a qualified release vintage cannot enter historical features.
    """
    if cutoff.tzinfo is None:
        raise ValueError("aware economic cutoff required")
    accepted, rejected = [], Counter()
    for index, row in enumerate(observations):
        if index >= 10000:
            raise ValueError("bounded economic vintage input required")
        try:
            if urlsplit(row["source_url"]).scheme != "https" or urlsplit(row["source_url"]).hostname not in OFFICIAL_HOSTS:
                raise ValueError("official_economic_source_required")
            release = datetime.fromisoformat(row["release_at"])
            retrieved = datetime.fromisoformat(row["retrieved_at"])
            vintage = datetime.fromisoformat(row["vintage_at"])
            if any(x.tzinfo is None for x in (release, retrieved, vintage)):
                raise ValueError("exact_aware_release_and_vintage_times_required")
            if max(release, retrieved, vintage) > cutoff:
                raise ValueError("future_or_unavailable_economic_vintage")
            if row.get("is_revision") is not False or row.get("release_status") != "initial":
                raise ValueError("revised_or_unknown_release_withheld")
            if not row.get("series_id") or not row.get("units") or not row.get("raw_evidence_sha256"):
                raise ValueError("economic_series_units_and_provenance_required")
            if len(row["raw_evidence_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["raw_evidence_sha256"]):
                raise ValueError("economic_raw_hash_required")
            value = float(row["value"])
            if isinstance(row["value"], bool) or not math.isfinite(value):
                raise ValueError("finite_economic_value_required")
            accepted.append({**row, "value": value, "available_at": max(release, retrieved, vintage).isoformat()})
        except (ValueError, KeyError, TypeError) as error:
            reason = str(error) if isinstance(error, ValueError) else "missing_economic_vintage_fields"
            rejected[reason[:120]] += 1
    return {"accepted": accepted, "rejections": dict(rejected), "certification_authority": False,
            "limitations": "Source hashes require independent raw replay; this structural qualifier does not establish authenticity"}


def forecast_economic(contract, evidence, *, cutoff):
    # Meeting calendars and the current target rate do not independently establish
    # the probability of a future FOMC vote. No numerical fallback is provided.
    return {"status": "withheld", "probability": None, "domain": "economics",
            "reasons": ["qualified_release_vintages_and_independent_calibrated_model_required"],
            "brier": None, "log_loss": None, "trading_authority": False}
