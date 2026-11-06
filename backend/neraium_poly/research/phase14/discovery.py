"""Bounded category-aware public discovery; metadata is never executable liquidity."""

import asyncio
import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from time import monotonic
from typing import get_args
from urllib.parse import urlsplit

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import Domain, DomainMarket

GAMMA = "https://gamma-api.polymarket.com"
DOMAINS = get_args(Domain)
TAG_SLUGS = {
    "weather": ("weather", "climate", "temperature", "hurricanes"),
    "crypto": ("crypto", "cryptocurrency", "bitcoin", "ethereum"),
    "finance": ("finance", "financial-markets", "stocks", "business"),
    "economics": ("economy", "economics", "fed", "fomc", "fed-rates", "macro-indicators", "economic-policy"),
    "politics": ("politics", "elections", "us-politics", "government"),
    "sports": ("sports", "nfl", "nba", "nhl", "mlb", "soccer", "tennis", "ncaa"),
    "esports": ("esports", "counter-strike-2", "league-of-legends", "dota-2", "valorant"),
    "technology": ("tech", "technology", "ai", "artificial-intelligence"),
    "science": ("science", "space", "space-exploration", "nasa"),
    "geopolitics": ("geopolitics", "international-affairs", "military"),
    "entertainment": ("pop-culture", "entertainment", "movies", "music", "oscars"),
}
TAG_DOMAINS = {slug: domain for domain, slugs in TAG_SLUGS.items() for slug in slugs}
HOST_DOMAINS = {
    "binance.com": "crypto", "coinbase.com": "crypto", "kraken.com": "crypto",
    "federalreserve.gov": "economics", "bls.gov": "economics", "bea.gov": "economics",
    "fred.stlouisfed.org": "economics", "treasury.gov": "economics",
    "noaa.gov": "weather", "weather.gov": "weather", "aviationweather.gov": "weather",
    "wunderground.com": "weather", "nba.com": "sports", "nfl.com": "sports",
    "nhl.com": "sports", "mlb.com": "sports", "atptour.com": "sports",
    "lolesports.com": "esports", "hltv.org": "esports", "gol.gg": "esports",
    "fec.gov": "politics", "congress.gov": "politics", "senate.gov": "politics",
    "nasa.gov": "science", "spacex.com": "science",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _slug(value):
    return re.sub(r"[ _]+", "-", str(value).strip().casefold())


def _tags(raw):
    result = []
    for source in (raw, *[e for e in raw.get("events", []) if isinstance(e, dict)]):
        category = source.get("category")
        if isinstance(category, str):
            result.append({"slug": _slug(category), "basis": "structured_category"})
        for tag in source.get("tags", []) or []:
            if isinstance(tag, dict):
                result.append({"slug": _slug(tag.get("slug", tag.get("label", ""))), "id": tag.get("id"),
                               "basis": "structured_tag"})
    return result


def _domain(raw):
    tags = _tags(raw)
    primary = {TAG_DOMAINS[t["slug"]] for t in tags if t["basis"] == "structured_category" and t["slug"] in TAG_DOMAINS}
    domains = primary or {TAG_DOMAINS[t["slug"]] for t in tags if t["slug"] in TAG_DOMAINS}
    # Generic and specialized tags can coexist without constituting independent categories.
    if "esports" in domains:
        domains.discard("sports")
    if "crypto" in domains:
        domains.discard("finance")
    if "economics" in domains:
        domains.discard("finance")
    if "geopolitics" in domains:
        domains.discard("politics")
    if len(domains) == 1:
        return next(iter(domains)), "structured_category" if primary else "structured_tag", False, tags, []
    if len(domains) > 1:
        return "other", "conflicting_structured_domains", True, tags, sorted(domains)
    host = (urlsplit(str(raw.get("resolutionSource") or "")).hostname or "").casefold()
    matches = {d for h, d in HOST_DOMAINS.items() if host == h or host.endswith("." + h)}
    if len(matches) == 1:
        return next(iter(matches)), "explicit_resolution_host", False, tags, []
    # Keywords are suggestions for review, never promoted to observed taxonomy.
    question = str(raw.get("question") or "").casefold()
    proposals = sorted({domain for domain, words in {
        "weather": ("temperature", "rainfall", "snowfall", "hurricane"),
        "crypto": ("bitcoin", "ethereum"), "politics": ("election", "president"),
        "technology": ("artificial intelligence", "openai"), "science": ("space mission", "nasa"),
        "geopolitics": ("ceasefire", "invasion"), "entertainment": ("oscar", "grammy"),
    }.items() if any(word in question for word in words)})
    return "other", "unclassified_keyword_suggestions_only" if proposals else "insufficient_structured_metadata", True, tags, proposals


def _array(value):
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, (tuple, list)) or len(value) > 200:
        raise ValueError("bounded outcome identities required")
    return tuple(str(v) for v in value)


def _number(raw, *keys):
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if not isinstance(value, bool) and math.isfinite(parsed) and parsed >= 0 else None
    return None


def classify_market(raw, received_at):
    """Classify an actual Gamma metadata observation; unknown fields remain unknown."""
    if received_at.tzinfo is None or not isinstance(raw, dict):
        raise ValueError("aware metadata observation required")
    tokens = _array(raw.get("positionIds") if raw.get("version") == "v2" else raw.get("clobTokenIds", ()))
    outcomes = _array(raw.get("outcomes", ()))
    event = raw.get("eventId") or next((e.get("id") for e in raw.get("events", []) if isinstance(e, dict) and e.get("id")), None)
    if not tokens or len(set(tokens)) != len(tokens) or any(not t for t in tokens) or len(tokens) != len(outcomes):
        raise ValueError("complete distinct outcome tokens required")
    if not event or not raw.get("id") or not raw.get("question"):
        raise ValueError("stable event/market/question required")
    domain, basis, review, tags, proposals = _domain(raw)
    rules = str(raw.get("description") or "")
    status = "resolved" if raw.get("resolved") is True or raw.get("umaResolutionStatus") == "resolved" else (
        "closed" if raw.get("closed") is True else "active" if raw.get("active") is True and raw.get("closed") is False else "unknown"
    )
    metadata = {
        "observed_tags": tags, "provisional_domains": proposals, "outcomes": outcomes,
        "liquidity_usd": _number(raw, "liquidityNum", "liquidity"),
        "volume_24h_usd": _number(raw, "volume24hr", "volume_24hr"),
        "volume_total_usd": _number(raw, "volumeNum", "volume"),
        "provider_updated_at": raw.get("updatedAt"), "provider_created_at": raw.get("createdAt"),
        "end_time": raw.get("endDate"), "enable_order_book": raw.get("enableOrderBook"),
        "accepting_orders": raw.get("acceptingOrders"), "spread": None, "bid_depth": None,
        "ask_depth": None, "executable_quotes_verified": False,
        "availability_basis": "actual_metadata_retrieval", "independent_evidence_available": False,
        "classification_only_not_contract_qualification": True,
    }
    values = {
        "timestamp": received_at, "available_at": received_at, "source": GAMMA,
        "event_id": str(event), "market_id": str(raw["id"]), "token_ids": tokens,
        "domain": domain, "classification_basis": basis, "classification_review_required": review,
        "question": str(raw["question"]), "resolution_rules": rules,
        "resolution_source": str(raw.get("resolutionSource") or ""),
        "rules_sha256": hashlib.sha256(rules.encode()).hexdigest(), "status": status,
        "metadata": metadata,
        "support_status": "domain_adapter_requires_exact_contract_qualification" if domain in {
            "weather", "crypto", "finance", "economics", "sports"
        } else "evidence_only_human_review",
    }
    serial = {**values, "timestamp": received_at.isoformat(), "available_at": received_at.isoformat()}
    return DomainMarket(id=digest(serial), **values)


def classify_snapshot(market, now):
    """Project existing normalized records without inventing structured tags or freshness."""
    market = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    if now.tzinfo is None or market.available_at > now or market.timestamp > now:
        raise ValueError("nonfuture normalized metadata required")
    raw = {"id": market.market_id, "eventId": market.event_id, "clobTokenIds": [market.token_id],
           "outcomes": [market.outcome], "question": market.question, "description": market.resolution_rules,
           "resolutionSource": market.resolution_source, "endDate": market.end_time.isoformat() if market.end_time else None,
           "active": market.status == "active", "closed": market.status in {"closed", "resolved"},
           "resolved": market.status == "resolved"}
    value = classify_market(raw, market.available_at).model_dump()
    value["timestamp"] = market.timestamp
    value["metadata"].update({"normalized_snapshot_projection": True, "source_record_id": market.id,
                              "metadata_age_seconds": (now-market.available_at).total_seconds(),
                              "freshness": "stale" if (now-market.available_at).total_seconds() > 3600 else "metadata_observed"})
    if value["metadata"]["freshness"] == "stale":
        value["support_status"] = "stale_metadata_no_forecast_eligibility"
    value["id"] = digest({**value, "timestamp": value["timestamp"].isoformat(), "available_at": value["available_at"].isoformat()})
    return DomainMarket.model_validate(value)


class DomainDiscovery:
    """Read-only, tag-aware metadata collection; existing subscriptions are not expanded."""

    def __init__(self, *, client=None, clock=None, max_requests=16, byte_budget=16*1024**2, rate=2):
        if type(max_requests) is not int or not 2 <= max_requests <= 16 or type(byte_budget) is not int or not 1024 <= byte_budget <= 16*1024**2 or isinstance(rate, bool) or not 0 < rate <= 2:
            raise ValueError("bounded public discovery required")
        self.client = client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self.owns_client = client is None
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_requests, self.byte_budget, self.rate = max_requests, byte_budget, rate
        self.responses, self.errors, self.requests, self.bytes = [], [], 0, 0
        self._next = 0.0
        self._lock = asyncio.Lock()
        self._discover_lock = asyncio.Lock()

    async def _get(self, path, params=None):
        if path != "/events" and path != "/tags" and not re.fullmatch(r"/tags/slug/[a-z-]+", path):
            raise ValueError("unapproved metadata endpoint")
        async with self._lock:
            if self.requests >= self.max_requests or self.bytes >= self.byte_budget:
                raise ValueError("discovery_request_or_byte_budget")
            await asyncio.sleep(max(0, self._next-monotonic()))
            self._next = monotonic() + 1/self.rate
            self.requests += 1
            async with self.client.stream("GET", GAMMA+path, params=params, follow_redirects=False) as response:
                response.raise_for_status()  # 429/503 fail closed; no unbounded retry.
                if int(response.headers.get("content-length", "0")) > min(4*1024**2, self.byte_budget-self.bytes):
                    raise ValueError("discovery_response_byte_budget")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > min(4*1024**2, self.byte_budget-self.bytes):
                        raise ValueError("discovery_response_byte_budget")
            observed = self.clock()
            payload = json.loads(body)
            self.bytes += len(body)
            self.responses.append({"path": path, "params": params or {}, "received_at": observed.isoformat(),
                                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                                   "raw_utf8": body.decode("utf-8"), "payload": payload})
            return payload, observed

    async def discover(self, *, max_markets=200):
        async with self._discover_lock:
            return await self._discover(max_markets=max_markets)

    async def _discover(self, *, max_markets=200):
        if type(max_markets) is not int or not 1 <= max_markets <= 200:
            raise ValueError("at most200 selected metadata markets required")
        self.responses, self.errors, self.requests, self.bytes = [], [], 0, 0
        tags, candidates, queried = {}, {}, []

        def accept_events(events, at):
            if not isinstance(events, list) or len(events) > 500:
                raise ValueError("bounded event list required")
            for event in events:
                if not isinstance(event, dict):
                    continue
                for tag in event.get("tags", []) or []:
                    if isinstance(tag, dict) and _slug(tag.get("slug", "")) in TAG_DOMAINS and tag.get("id"):
                        tags.setdefault(TAG_DOMAINS[_slug(tag["slug"])], tag)
                for raw in event.get("markets", [])[:1000]:
                    if len(candidates) >= 2000:
                        return
                    try:
                        merged = {**raw, "events": [{"id": event.get("id"), "tags": event.get("tags", []),
                                                    "category": event.get("category")}], "eventId": event.get("id")}
                        value = classify_market(merged, at)
                        if value.status != "active" or raw.get("enableOrderBook") is False or raw.get("acceptingOrders") is False:
                            continue
                        candidates.setdefault(value.market_id, value)
                    except (ValueError, TypeError, KeyError) as error:
                        if len(self.errors) < 32:
                            self.errors.append(str(error)[:120])
                    if len(candidates) >= 2000:
                        return
        try:
            rows, _ = await self._get("/tags", {"limit": 100, "offset": 0, "order": "id", "ascending": "true"})
            if not isinstance(rows, list):
                raise TypeError("invalid public tags")
            for tag in rows[:500]:
                if isinstance(tag, dict) and _slug(tag.get("slug", "")) in TAG_DOMAINS and tag.get("id"):
                    tags.setdefault(TAG_DOMAINS[_slug(tag["slug"])], tag)
            rows, at = await self._get("/events", {"active": "true", "closed": "false", "limit": 2,
                                                       "order": "volume24hr", "ascending": "false"})
            accept_events(rows, at)
            # Resolve at most three absent canonical tags; IDs must come from the provider.
            for domain in [d for d in TAG_SLUGS if d not in tags][:3]:
                if self.requests >= self.max_requests-1:
                    break
                try:
                    row, _ = await self._get("/tags/slug/"+TAG_SLUGS[domain][0])
                    if isinstance(row, dict) and row.get("id") and TAG_DOMAINS.get(_slug(row.get("slug", ""))) == domain:
                        tags[domain] = row
                except httpx.HTTPStatusError as error:
                    if error.response.status_code != 404:
                        raise
                    self.errors.append("canonical_tag_unavailable:"+domain)
            for domain in TAG_SLUGS:
                if domain not in tags or self.requests >= self.max_requests:
                    continue
                rows, at = await self._get("/events", {"tag_id": str(tags[domain]["id"]), "active": "true",
                                                       "closed": "false", "limit": 2, "order": "volume24hr",
                                                       "ascending": "false"})
                queried.append(domain)
                accept_events(rows, at)
        except (ValueError, TypeError, KeyError, httpx.HTTPError) as error:
            self.errors.append(type(error).__name__+":"+str(error)[:120])
        buckets = defaultdict(deque)
        for market in sorted(candidates.values(), key=lambda m: (-(m.metadata["liquidity_usd"] or 0),
                                                                 -(m.metadata["volume_24h_usd"] or 0), m.market_id)):
            buckets[market.domain].append(market)
        selected = []
        while len(selected) < max_markets and any(buckets.values()):
            for domain in DOMAINS:
                if buckets[domain] and len(selected) < max_markets:
                    selected.append(buckets[domain].popleft())
        report = {"observed_at": self.clock().isoformat(), "status": "metadata_research_only",
                  "requests": self.requests, "response_bytes": self.bytes, "request_rate_cap": self.rate,
                  "candidate_markets": len(candidates), "selected_markets": len(selected),
                  "candidate_categories": dict(Counter(m.domain for m in candidates.values())),
                  "selected_categories": dict(Counter(m.domain for m in selected)),
                  "categories_queried": queried, "actual_tag_ids": {d: str(t["id"]) for d, t in tags.items()},
                  "errors": self.errors[:32], "universe_complete": False,
                  "selection": "bounded tag-aware category round robin, liquidity priority within category",
                  "executable_markets_verified": 0, "independent_forecasts": 0,
                  "raw_evidence_persistence": "bounded response objects in memory; caller must persist before forecast qualification",
                  "subscription_expansion_authority": False, "trading_authority": False}
        return {"markets": selected, "report": report, "responses": self.responses}

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
