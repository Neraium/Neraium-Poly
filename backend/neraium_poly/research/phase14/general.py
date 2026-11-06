"""Extensible political/technology/science evidence, never probabilities from prose."""
import hashlib
from urllib.parse import urlsplit

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.finance import digest

DOMAINS = {"politics", "technology", "science", "geopolitics", "entertainment", "other", "esports"}


def map_general(market, *, domain, now):
    if domain not in DOMAINS:
        raise ValueError("general_domain_not_supported")
    m = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    if now.tzinfo is None or m.timestamp > now or m.available_at > now:
        raise ValueError("noncausal_general_contract")
    reasons = ["exact_event_entities_and_resolution_conditions_require_review", "no_validated_general_probability_model"]
    if not m.resolution_rules or not m.resolution_source:
        reasons.append("resolution_rules_or_source_missing")
    return DomainContract(id=digest([m.id, domain, "general-contract-v1"]), timestamp=now, available_at=now,
        source="neraium-poly/general-contract/v1", domain=domain, event_id=m.event_id, market_id=m.market_id,
        token_id=m.token_id, contract_type="reviewed_general_event_required", probability_semantics="unsupported",
        rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
        parameters={"question": m.question, "resolution_source": m.resolution_source,
                    "source_is_not_automatically_an_authoritative_outcome": True}, compatible=False,
        review_required=True, reasons=tuple(reasons))


def qualify_general_evidence(contract, evidence, *, cutoff, reviewer=None):
    c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
    if cutoff.tzinfo is None:
        raise ValueError("aware general evidence cutoff required")
    accepted, reasons = [], []
    for item in evidence:
        e = DomainEvidence.model_validate(item.model_dump() if isinstance(item, DomainEvidence) else item)
        if (e.domain != c.domain or max(e.available_at, e.retrieved_at, e.timestamp) > cutoff
            or digest(e.payload) != e.content_sha256 or not e.independent_of_polymarket):
            reasons.append("general_evidence_identity_provenance_or_availability")
            continue
        parsed = urlsplit(e.source)
        if parsed.scheme != "https" or not parsed.hostname or "polymarket" in parsed.hostname:
            reasons.append("general_independent_https_source_required")
            continue
        if reviewer is None or reviewer(c, e) is not True:
            reasons.append("general_source_and_event_interpretation_review_required")
            continue
        accepted.append(e.id)
    return {"evidence_ids": accepted, "reasons": sorted(set(reasons)), "numerical_probability_supported": False,
            "research_only": True, "trading_authority": False, "certification_authority": False}


def forecast_general(contract, evidence, *, cutoff):
    return {"domain": contract.domain, "probability": None, "status": "withheld",
            "reasons": ["timestamped_news_does_not_supply_calibrated_event_probability"],
            "brier": None, "log_loss": None, "trading_authority": False}
