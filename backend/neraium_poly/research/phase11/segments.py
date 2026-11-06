"""Descriptive current-market segment quality; never point-in-time model context."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import httpx

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.research.phase11.contracts import ExperimentSpec

GAMMA = "https://gamma-api.polymarket.com"
TAG_MAP = {
    "sports": "Sports",
    "esports": "Sports",
    "politics": "Politics",
    "elections": "Politics",
    "economics": "Economics",
    "economy": "Economics",
    "finance": "Financial markets",
    "financials": "Financial markets",
    "crypto": "Financial markets",
    "weather": "Weather",
    "entertainment": "Entertainment",
    "pop culture": "Entertainment",
}


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("aware capture time required")
    return at.astimezone(UTC)


def acquire_event_metadata(frame, output, *, max_requests=50, max_bytes=25 * 1024**2, client=None):
    """Fixed official GET endpoints, bounded bytes/rate and content-bound raw evidence.

    This is current category enrichment only. Acquisition times cannot be
    backdated to a quote or used as historical decision-time features.
    """
    output = Path(output)
    if not 1 <= max_requests <= 60 or not 1024 <= max_bytes <= 25 * 1024**2:
        raise ValueError("bounded metadata acquisition required")
    if output.exists():
        raise ValueError("new metadata evidence directory required")
    if shutil.disk_usage(output.parent).free < 8 * 1024**3 + max_bytes:
        raise ValueError("free disk floor")
    output.mkdir(parents=True)
    (output / "raw").mkdir()
    events = Counter(str(m["event_id"]) for m in frame["markets"])
    selected = sorted(events, key=lambda e: (-events[e], e))[:max_requests]
    owned = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False)
    records, errors, used = {}, [], 0
    try:
        for event_id in selected:
            if not event_id.isdecimal():
                errors.append({"event_id": event_id, "reason": "non-numeric public event identity"})
                continue
            url = f"{GAMMA}/events/{event_id}"
            try:
                body = bytearray()
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        if used + len(chunk) > max_bytes:
                            raise ValueError("metadata byte budget")
                        used += len(chunk)
                        body.extend(chunk)
                received = datetime.now(UTC).isoformat()
                digest = hashlib.sha256(body).hexdigest()
                path = output / "raw" / f"{event_id}-{digest}.json"
                path.write_bytes(body)
                raw = json.loads(body)
                if str(raw.get("id")) != event_id:
                    raise ValueError("official event identity mismatch")
                tags = [
                    str(t["label"]) for t in raw.get("tags", []) if isinstance(t, dict) and t.get("label")
                ]
                records[event_id] = {
                    "event_id": event_id,
                    "source": url,
                    "available_at": received,
                    "raw_path": str(path.relative_to(output)),
                    "raw_sha256": digest,
                    "tags": tags,
                    "official_category": raw.get("category"),
                    "market_ids": [
                        str(m["id"]) for m in raw.get("markets", []) if isinstance(m, dict) and m.get("id")
                    ],
                    "volume24hr_event_usd": raw.get("volume24hr"),
                    "closed": raw.get("closed"),
                }
            except (httpx.HTTPError, ValueError, KeyError) as error:
                errors.append({"event_id": event_id, "reason": type(error).__name__})
            time.sleep(0.25)
    finally:
        if owned:
            client.close()
    result = {
        "schema_version": "1.0",
        "acquired_at": datetime.now(UTC).isoformat(),
        "purpose": "current descriptive segment enrichment, unavailable at earlier decisions",
        "request_bound": max_requests,
        "attempted_events": len(selected),
        "response_bytes": used,
        "records": records,
        "errors": errors,
        "certification_authority": False,
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _category(market, official):
    evidence = official.get(market.event_id, {})
    if (
        market.market_id not in evidence.get("market_ids", [])
        or evidence.get("source") != f"{GAMMA}/events/{market.event_id}"
        or not isinstance(evidence.get("raw_sha256"), str)
        or len(evidence["raw_sha256"]) != 64
        or not evidence.get("available_at")
    ):
        return "Unknown", "unavailable", []
    _at(evidence["available_at"])
    tags = evidence.get("tags", [])
    candidates = [str(evidence.get("official_category") or "").casefold()] + [str(t).casefold() for t in tags]
    matches = list(dict.fromkeys(TAG_MAP[t] for t in candidates if t in TAG_MAP))
    if len(matches) != 1:
        return "Unknown", "ambiguous official tags" if matches else "unmapped official tags", tags
    return matches[0], "official tag mapping (descriptive)", tags


def run_segments(frame, *, captured_at=None, official_tags=None):
    """Compare fresh executable quote quality without inferring settlement reliability."""
    if frame.get("mode") != "real_market_data":
        raise ValueError("real public frame required")
    now = _at(captured_at or frame["available_at"])
    markets = [MarketSnapshot.model_validate(m) for m in frame["markets"]]
    books = {b["token_id"]: OrderBookSnapshot.model_validate(b) for b in frame["books"]}
    if len(books) != len(frame["books"]) or len({m.token_id for m in markets}) != len(markets):
        raise ValueError("ambiguous frame identities")
    records = (official_tags or {}).get("records", official_tags or {})
    groups = defaultdict(list)
    details = []
    for market in markets:
        segment, basis, tags = _category(market, records)
        b = books.get(market.token_id)
        quality = assess_book(b, now, max_spread=0.05, expected_token=market.token_id)
        identity = bool(
            b
            and b.market_id == market.market_id
            and b.exchange == "polymarket"
            and b.source
            in {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
        )
        fresh = quality.healthy and identity
        spread = b.asks[0].price - b.bids[0].price if b and b.asks and b.bids else None
        ask_depth = sum(level.size * level.price for level in b.asks) if fresh else None
        bid_depth = sum(level.size * level.price for level in b.bids) if fresh else None
        min_lot = market.min_order_size * b.asks[0].price if fresh else None
        duration = (market.end_time - now).total_seconds() if market.end_time else None
        metadata = bool(
            market.status == "active"
            and market.resolution_rules
            and market.resolution_source
            and (duration is None or duration > 120)
        )
        result = {
            "market_id": market.market_id,
            "token_id": market.token_id,
            "event_id": market.event_id,
            "segment": segment,
            "classification_basis": basis,
            "official_tags": tags,
            "classification_available_at": records.get(market.event_id, {}).get("available_at"),
            "classification_source": records.get(market.event_id, {}).get("source"),
            "classification_raw_sha256": records.get(market.event_id, {}).get("raw_sha256"),
            "book_id": b.id if b else None,
            "source_timestamp": b.timestamp.isoformat() if b else None,
            "receipt_timestamp": b.available_at.isoformat() if b else None,
            "healthy_executable_quote": fresh,
            "quality_reasons": list(quality.reasons),
            "spread": spread,
            "displayed_bid_depth_usd": bid_depth,
            "displayed_ask_depth_usd": ask_depth,
            "min_lot_within_five_dollars": min_lot is not None and min_lot <= 5,
            "metadata_eligible": metadata,
            "rules_present": bool(market.resolution_rules and market.resolution_source),
            "seconds_to_scheduled_end": duration,
            "horizon": "ended"
            if duration is not None and duration <= 0
            else "under_24h"
            if duration is not None and duration <= 86400
            else "longer_or_unknown",
            "resolution_reliability": None,
            "independent_evidence_sufficient": None,
            "executable_net_edge": None,
            "profitability": None,
        }
        groups[segment].append(result)
        details.append(result)
    summary = []
    for segment, rows in groups.items():
        spreads = [r["spread"] for r in rows if r["healthy_executable_quote"]]
        eligible = sum(
            r["metadata_eligible"] and r["healthy_executable_quote"] and r["min_lot_within_five_dollars"]
            for r in rows
        )
        summary.append(
            {
                "segment": segment,
                "markets": len({r["market_id"] for r in rows}),
                "events": len({r["event_id"] for r in rows}),
                "tokens": len(rows),
                "fresh_executable_quotes": len(spreads),
                "rules_present": sum(r["rules_present"] for r in rows),
                "metadata_eligible": sum(r["metadata_eligible"] for r in rows),
                "static_research_suitable_tokens": eligible,
                "median_spread": median(spreads) if spreads else None,
                "median_displayed_bid_depth_usd": median(
                    [r["displayed_bid_depth_usd"] for r in rows if r["healthy_executable_quote"]]
                )
                if spreads
                else None,
                "median_displayed_ask_depth_usd": median(
                    [r["displayed_ask_depth_usd"] for r in rows if r["healthy_executable_quote"]]
                )
                if spreads
                else None,
                "horizons": dict(Counter(r["horizon"] for r in rows)),
                "historical_evidence_sufficient": None,
                "resolution_reliability": None,
                "market_volume_usd": None,
                "cost_adjusted_advantage": None,
                "priority_basis": "eligible fresh quotes with rules and minimum lot <=$5; not expected profit",
            }
        )
    summary.sort(key=lambda row: (-row["static_research_suitable_tokens"], row["segment"]))
    frame_sha = hashlib.sha256(json.dumps(frame, sort_keys=True).encode()).hexdigest()
    spec = ExperimentSpec(
        experiment_id="phase11-segment-quality-v1",
        hypothesis="Some current segments may offer better observed data quality for further research, without asserting advantage",
        dataset_sha256=frame_sha,
        model_version="official-event-tag-quality-map-v1",
        feature_definitions={
            "spread": "actual observed ask minus bid",
            "depth": "sum displayed USD levels on each side",
            "segment": "current official Gamma event tag mapping; descriptive only",
        },
        target_definitions={
            "research_suitability": "fresh identity-matched public quote, active rules and minimum lot notional <=$5; no fee/forecast/risk approval implied"
        },
        split_policy="descriptive fixed snapshot; no training, validation or heldout performance claim",
        grouping={
            "unit": "outcome token",
            "event_group": "reported event_id",
            "independence_reviewed": False,
        },
        transaction_cost_assumptions={"trade_returns": None, "depth_survival_and_queue_position": "unknown"},
        failure_conditions=(
            "missing/ambiguous official tags stay Unknown",
            "stale/incomplete/mismatched books cannot support liquidity comparisons",
        ),
        limitations=(
            "single snapshot is not robustness across regimes",
            "no historical settlement reliability or profitability estimate",
        ),
    )
    return {
        "schema_version": "1.0",
        "experiment_id": "phase11-segment-quality-v1",
        "experiment_spec": spec.model_dump(mode="json"),
        "confidence_intervals": None,
        "confidence_interval_reason": "Descriptive snapshot, no independently sampled performance target",
        "captured_at": now.isoformat(),
        "source_frame_id": frame["id"],
        "source_frame_sha256": hashlib.sha256(json.dumps(frame, sort_keys=True).encode()).hexdigest(),
        "category_enrichment_sha256": hashlib.sha256(
            json.dumps(official_tags or {}, sort_keys=True).encode()
        ).hexdigest(),
        "market_count": len({m.market_id for m in markets}),
        "token_count": len(markets),
        "category_policy": "Official event membership plus explicit tag mapping; unknown or ambiguous is not inferred from question text",
        "segments": summary,
        "observations": details,
        "qualification_thresholds_changed": False,
        "certification_authority": False,
        "automatic_promotion": False,
        "limitations": [
            "Current categories are descriptive enrichment, never backdated decision-time features",
            "Displayed depth is not queue position, survival through latency, or actual fill evidence",
            "Rules present does not verify settlement correctness or historical rule versions",
            "No segment profitability, resolution reliability, or independent historical sufficiency is asserted",
            "Normalized market snapshots contain no volume; event volume cannot be summed as market volume",
        ],
    }
