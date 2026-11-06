"""Fair same-cutoff binary domain scoring; no review/proof means null metrics."""

from collections import Counter, defaultdict
from math import log, sqrt
from statistics import mean

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase14.contracts import DomainForecast


def evaluate_domain_forecasts(
    forecasts,
    outcomes,
    *,
    forecast_validator=None,
    outcome_validator=None,
    independence_validator=None,
    minimum_events=20,
):
    if type(minimum_events) is not int or not 20 <= minimum_events <= 100000:
        raise ValueError("at least20reviewed independent events required for headline research metrics")
    parsed = []
    for index, value in enumerate(forecasts):
        if index >= 20000:
            raise ValueError("bounded domain cohort required")
        parsed.append(
            DomainForecast.model_validate(value.model_dump() if isinstance(value, DomainForecast) else value)
        )
    verified = {}
    rejections = Counter()
    for index, value in enumerate(outcomes):
        if index >= 20000:
            raise ValueError("bounded outcome cohort required")
        o = VerifiedEventOutcome.model_validate(
            value.model_dump() if isinstance(value, VerifiedEventOutcome) else value
        )
        if (
            outcome_validator is None
            or outcome_validator(o) is not True
            or content_sha256(o.verification) != o.proof_sha256
        ):
            rejections["verified_outcome_proof_required"] += 1
            continue
        key = (o.event_id, o.market_id, o.token_id)
        if key in verified and verified[key] != o:
            raise ValueError("conflicting domain outcome requires review")
        verified[key] = o
    rows = defaultdict(list)
    seen = set()
    seen_events = set()
    for f in sorted(parsed, key=lambda f: (f.timestamp, f.id)):
        if forecast_validator is None or forecast_validator(f) is not True:
            rejections["original_forecast_model_replay_required"] += 1
            continue
        if f.probability_semantics != "binary_event_probability":
            rejections["separate_nonbinary_scoring_required"] += 1
            continue
        o = verified.get((f.event_id, f.market_id, f.token_id))
        if o is None:
            continue
        if f.timestamp >= o.settled_at or f.rules_sha256 != o.resolution_rules_sha256:
            rejections["noncausal_or_changed_rules"] += 1
            continue
        if independence_validator is None or independence_validator(f) is not True:
            rejections["independent_group_review_required"] += 1
            continue
        try:
            b = OrderBookSnapshot.model_validate(f.contemporaneous_market["book"])
            if (
                b.source not in PUBLIC_BOOK_SOURCES
                or b.exchange != "polymarket"
                or (b.market_id, b.token_id) != (f.market_id, f.token_id)
                or not assess_book(b, f.timestamp, max_spread=0.05).healthy
            ):
                raise ValueError("invalid baseline")
            baseline = (b.bids[0].price + b.asks[0].price) / 2
        except (KeyError, ValueError, IndexError):
            rejections["original_comparable_book_required"] += 1
            continue
        identity = (f.domain, f.model_version, f.model_sha256, f.feature_version)
        key = (identity, f.dependency_group)
        event_key = (identity, f.event_id)
        if key in seen or event_key in seen_events:
            rejections["correlated_or_repeated_event_group"] += 1
            continue
        seen.add(key)
        seen_events.add(event_key)
        rows[identity].append((f.probability, baseline, o.payout))
    reports = []
    for identity, data in rows.items():
        enough = len(data) >= minimum_events
        clip = lambda p: min(1 - 1e-12, max(1e-12, p))
        delta = mean((p - y) ** 2 - (b - y) ** 2 for p, b, y in data)
        radius = sqrt(2 * log(40) / len(data)) if enough else None
        reliability = []
        for i in range(10):
            group = [(p, y) for p, _b, y in data if min(9, int(p * 10)) == i]
            if group and enough:
                reliability.append(
                    {
                        "bin": i,
                        "count": len(group),
                        "mean_forecast": mean(p for p, y in group),
                        "mean_outcome": mean(y for p, y in group),
                    }
                )
        reports.append(
            {
                "domain": identity[0],
                "model_version": identity[1],
                "model_sha256": identity[2],
                "feature_version": identity[3],
                "independent_events": len(data),
                "brier": mean((p - y) ** 2 for p, b, y in data) if enough else None,
                "market_brier": mean((b - y) ** 2 for p, b, y in data) if enough else None,
                "log_loss": mean(-y * log(clip(p)) - (1 - y) * log(1 - clip(p)) for p, b, y in data)
                if enough
                else None,
                "paired_brier_difference": delta if enough else None,
                "paired_difference_95_bound": [max(-1, delta - radius), min(1, delta + radius)]
                if enough
                else None,
                "reliability": reliability,
                "confidence_assumption": "reviewed independent event groups; dependence invalidates bound",
                "cost_adjusted_trading_potential": None,
                "certification_authority": False,
            }
        )
    return {
        "models": reports,
        "rejections": dict(rejections),
        "minimum_research_events": minimum_events,
        "certified_minimum_training_events": 100,
        "certified_minimum_heldout_events": 100,
        "comparison": "same forecast timestamp original book; never later market prices",
        "automatic_promotion": False,
        "trading_authority": False,
    }
