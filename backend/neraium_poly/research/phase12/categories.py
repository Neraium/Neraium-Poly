"""Evidence-led specialization; category ranking is not expected trading return."""

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from neraium_poly.research.phase12.dataset import load_dataset

CATEGORY_MAP = {
    "sports": "Sports",
    "tennis": "Sports",
    "ppa": "Sports",
    "weather": "Weather",
    "politics": "Politics",
    "finance": "Financial events",
    "up or down": "Financial events",
    "crypto": "Financial events",
    "bitcoin": "Financial events",
    "ethereum": "Financial events",
    "rut": "Financial events",
    "nya": "Financial events",
    "economics": "Economics",
    "esports": "Entertainment / esports",
    "entertainment": "Entertainment / esports",
}


def run_categories(dataset):
    if isinstance(dataset, (str, Path)):
        dataset = load_dataset(dataset)
    groups = defaultdict(list)
    for event in dataset["events"]:
        groups[CATEGORY_MAP.get(event.category.casefold(), "Other / unknown")].append(event)
    evidence = dataset["evidence"]
    outcomes = dataset["outcomes"]
    rows = []
    for name in (
        "Sports",
        "Weather",
        "Economics",
        "Financial events",
        "Politics",
        "Entertainment / esports",
        "Other / unknown",
    ):
        events = groups[name]
        ids = {e.market_id for e in events}
        contexts = [e for e in evidence if e.market_id in ids and e.kind == "external_context"]
        prices = [e for e in evidence if e.market_id in ids and e.kind == "market_price"]
        final = [e for e in outcomes if e.market_id in ids]
        selected = (name == "Sports" and bool(final) and len(events) >= 2) or (
            name == "Weather"
            and bool(contexts)
            and any(e.resolution_rules and e.resolution_source for e in events)
        )
        rows.append(
            {
                "category": name,
                "market_propositions": len(events),
                "parent_events": len({e.event_id for e in events}),
                "proposed_dependency_groups": len({e.dependency_group for e in events}),
                "reviewed_independent_events": sum(e.independence_reviewed for e in events),
                "official_api_outcome_groups": sum(
                    e.provenance.get("official_api_outcome_verified", False) for e in events
                ),
                "corroborated_exact_outcome_groups": len(final),
                "resolution_rules_and_source": sum(
                    bool(e.resolution_rules and e.resolution_source) for e in events
                ),
                "historical_price_rows": len(prices),
                "historical_book_rows": sum(e.market_id in ids and e.kind == "order_book" for e in evidence),
                "independent_external_observations": sum(e.independent_of_market_price for e in contexts),
                "historical_pit_external_context_qualified": 0,
                "resolution_reliability": None,
                "executable_historical_spread": None,
                "historical_liquidity": None,
                "forecast_skill": None,
                "certifiable_training_events": 0,
                "certifiable_heldout_events": 0,
                "primary_research_selection": selected,
                "selection_role": "outcome-linkage and prospective event study"
                if name == "Sports"
                else "station-rule and external-evidence prospective study"
                if name == "Weather"
                else "deferred",
                "rationale": {
                    "Sports": f"{len(final)} corroborated payouts among {len(events)} propositions, many distinct proposed parent groups, clear winner contracts; independent event review and predecision external features remain missing",
                    "Weather": f"{sum(e.independent_of_market_price for e in contexts)} authentic independent METAR observations and explicit station/temperature rule sources; {len(events)} events and {len(final)} corroborated outcomes, so prospective context-first research only",
                    "Financial events": "Numerous observations and finalized payouts but many repeated asset windows; proposed asset groups, unavailable PIT external drivers and depth prevent treating breadth as independent evidence",
                    "Politics": "520 historical prices belong to one event; repeated snapshots do not establish a training sample",
                    "Economics": "No event in this frozen historical corpus; current liquid contracts do not supply past vintage features or labels",
                    "Entertainment / esports": "Few prices and no corroborated payouts in this corpus; evidence completeness below selected alternatives",
                    "Other / unknown": "No verified classification or evidence superiority; remain unassigned",
                }[name],
            }
        )
    return {
        "schema_version": "1.0",
        "dataset_sha256": dataset["manifest"]["dataset_sha256"],
        "selected_categories": [r["category"] for r in rows if r["primary_research_selection"]],
        "selection_purpose": "Research suitability, not live strategy or profitability",
        "ranking_policy": "Prioritize distinct proposed event structures with corroborated outcomes (Sports) and independent source-measured context plus explicit rules (Weather); no invented weighted profit score",
        "categories": rows,
        "qualification_funnel": dataset["manifest"]["qualification_funnel"],
        "limitations": [
            "No category has qualified independent training or held-out events",
            "Proposed dependency groups are not independently reviewed events",
            "Historical executable books/spreads/liquidity and settlement reliability remain unsupported",
            "Station observations are not calibrated event forecasts; delayed acquisition is not past availability",
        ],
        "certification_authority": False,
        "automatic_promotion": False,
    }


def acquire_weather_context(output, *, client=None):
    """Archive current official EGLC METAR context without backdating or deriving probabilities.

    EGLC matches the station named in the two source weather-event resolution
    rules. These events are already closed; this acquisition is an external-source
    pipeline probe, not predecision evidence for those past events.
    """
    output = Path(output)
    if output.exists():
        raise ValueError("new external context directory required")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 8 * 1024**3 + 1024 * 1024:
        raise ValueError("external context free-disk floor")
    own = client is None
    client = client or httpx.Client(
        timeout=20,
        follow_redirects=False,
        headers={"User-Agent": "Neraium-Poly paper research https://github.com/Neraium/Neraium-Poly"},
    )
    url = "https://aviationweather.gov/api/data/metar"
    try:
        response = client.get(url, params={"ids": "EGLC", "format": "json", "hours": 2})
        received = datetime.now(UTC)
        raw = response.content
        if len(raw) > 1024 * 1024:
            raise ValueError("external context response budget")
        output.mkdir()
        (output / "response.json").write_bytes(raw)
        report = {
            "source": url,
            "params": {"ids": "EGLC", "format": "json", "hours": 2},
            "http_status": response.status_code,
            "received_at": received.isoformat(),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "requests": 1,
            "availability_basis": "collected_now",
            "historical_predecision_qualified": False,
            "probability_estimates": None,
            "event_outcome_labels": None,
            "limitation": "Current observations cannot be attributed to prior decisions or converted to calibrated event probabilities",
        }
        if response.is_success:
            values = json.loads(raw)
            if not isinstance(values, list):
                raise ValueError("METAR source schema unsupported")
            report["observations"] = len(values)
            report["stations"] = sorted({r.get("icaoId") for r in values if r.get("icaoId")})
            report["source_observation_times"] = [r.get("obsTime") for r in values]
        (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        if own:
            client.close()
