"""Bounded current-day event discovery; metadata never substitutes for executable books."""

import asyncio
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.data import assess_book
from neraium_poly.data.polymarket import CLOB, GAMMA, normalize_book, normalize_market
from neraium_poly.research.phase18.forecasting import map_event_contract

MAX_RESPONSE_BYTES = 1024**2
MAX_TOTAL_BYTES = 4 * 1024**2
ASSETS = ("bitcoin", "ethereum")


def _now():
    return datetime.now(UTC)


def _at(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware discovery cutoff required")
    return value.astimezone(UTC)


def _nonnegative(value):
    if isinstance(value, bool):
        return 0.
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else 0.
    except (TypeError, ValueError, OverflowError):
        return 0.


async def discover_forecast_markets(*, now, client=None, max_requests=3, max_candidates=40):
    """Query exact year-qualified ongoing event slugs, then public CLOB books.

    Prices affect collection priority only; they never enter a forecasting model.
    Every candidate is rechecked by the unchanged exact-rule Phase18 interpreter.
    ``markets`` are raw Gamma records ordered by native-book health then observed
    depth. ``health_by_market`` distinguishes executable-book preflight from
    metadata-only warmup candidates; neither grants forecast/trading authority.
    All retrieval times are actual receipt times, never the supplied request cutoff.
    Only the public read-only POST /books exists; no order endpoint is reachable.
    """
    now = _at(now)
    if now > _now():
        raise ValueError("future discovery cutoff")
    if type(max_requests) is not int or not 1 <= max_requests <= 6:
        raise ValueError("bounded public discovery request budget required")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 40:
        raise ValueError("bounded forecast candidate count required")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers={
        "User-Agent": "Neraium-Poly public research (https://github.com/Neraium/Neraium-Poly)"})
    provenance, reasons, candidates, conflicts = [], Counter(), {}, set()
    requests = total_bytes = 0
    last_request = None

    async def read(method, path, *, params=None, payload=None):
        nonlocal requests, total_bytes, last_request
        if requests >= max_requests:
            raise ValueError("public_discovery_request_budget_exhausted")
        if last_request is not None:
            await asyncio.sleep(max(0., .25 - (monotonic() - last_request)))
        last_request = monotonic();requests += 1
        origin = GAMMA if method == "GET" else CLOB
        if not ((method == "GET" and path == "/events") or (method == "POST" and path == "/books")):
            raise ValueError("public_read_only_discovery_route_required")
        started = _now()
        async with client.stream(method, origin+path, params=params, json=payload, follow_redirects=False) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("public_discovery_response_byte_limit")
            received = _now();total_bytes += len(body)
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("public_discovery_total_byte_limit")
            provenance.append({"method": method, "url": str(response.url), "request": params if method == "GET" else payload,
                "requested_at": started.isoformat(), "retrieved_at": received.isoformat(),
                "available_at": received.isoformat(), "http_status": response.status_code,
                "raw_bytes": len(body), "raw_sha256": hashlib.sha256(body).hexdigest(),
                "raw_response_utf8": body.decode("utf-8")})
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("public_discovery_redirect_forbidden")
            return json.loads(body), received

    try:
        day = now.astimezone(ZoneInfo("America/New_York"))
        for asset in ASSETS:
            if requests >= max_requests:
                reasons["asset_discovery_request_budget_exhausted"] += 1;break
            slug = f"what-price-will-{asset}-hit-on-{day.strftime('%B').lower()}-{day.day}-{day.year}"
            try:
                events, received = await read("GET", "/events", params={"slug": slug})
                if not isinstance(events, list) or len(events) > 4:
                    raise ValueError("bounded_event_response_array_required")
                if not events:
                    reasons["current_day_exact_event_unavailable"] += 1
                for event in events:
                    if not isinstance(event, dict) or event.get("slug") != slug or not event.get("id"):
                        reasons["event_slug_or_identity_mismatch"] += 1;continue
                    rows = event.get("markets", [])
                    if not isinstance(rows, list) or len(rows) > 100:
                        reasons["bounded_event_market_array_required"] += 1;continue
                    for raw in rows:
                        try:
                            if not isinstance(raw, dict) or raw.get("acceptingOrders") is not True or raw.get("enableOrderBook") is not True:
                                raise ValueError("market_not_explicitly_accepting_order_books")
                            parent = str(event["id"])
                            if raw.get("eventId") is not None and str(raw["eventId"]) != parent:
                                raise ValueError("market_parent_identity_mismatch")
                            native_parents = {str(x["id"]) for x in raw.get("events", []) if isinstance(x, dict) and x.get("id")}
                            if native_parents and native_parents != {parent}:
                                raise ValueError("market_parent_identity_mismatch")
                            bound = {**raw, "eventId": parent}
                            normalized = normalize_market(bound, received)
                            if len(normalized) != 2 or {m.outcome for m in normalized} != {"Yes", "No"}:
                                raise ValueError("exact_binary_event_required")
                            mapped = [map_event_contract(m, now=received) for m in normalized]
                            if not all(c.compatible and not c.review_required and c.contract_type == "binance_daily_low_barrier" for c in mapped):
                                reasons.update({r for c in mapped for r in c.reasons} or {"unsupported_event_contract"});continue
                            identity = normalized[0].market_id
                            if identity in conflicts:
                                raise ValueError("conflicting_discovery_market_identity")
                            if identity in candidates:
                                if candidates[identity][0] != bound:
                                    candidates.pop(identity);conflicts.add(identity)
                                    raise ValueError("conflicting_discovery_market_identity")
                                continue
                            candidates[identity] = bound, normalized
                        except (KeyError, TypeError, ValueError, OverflowError) as error:
                            reasons[str(error)[:100]] += 1
            except (httpx.HTTPError, ValueError, TypeError, KeyError, UnicodeError) as error:
                reasons["metadata_source_failure:"+type(error).__name__] += 1
                # Access/rate rejection must not be retried against another asset/source.
                break
        chosen = sorted(candidates.values(), key=lambda row: (-_nonnegative(row[0].get("liquidityNum", row[0].get("liquidity"))), str(row[0]["id"])))[:max_candidates]
        token_map = {m.token_id: m for _raw, records in chosen for m in records}
        books, seen, duplicates = {}, set(), set()
        if token_map and requests < max_requests:
            try:
                native_books, received = await read("POST", "/books", payload=[{"token_id": token} for token in sorted(token_map)])
                if not isinstance(native_books, list) or len(native_books) > 80:
                    raise ValueError("bounded_public_book_array_required")
                for raw in native_books:
                    try:
                        if not isinstance(raw, dict):
                            raise TypeError("native_book_mapping_required")
                        token = str(raw.get("asset_id", ""))
                        if token not in token_map:
                            raise ValueError("book_token_not_in_discovered_event")
                        if token in seen:
                            duplicates.add(token);books.pop(token, None)
                            raise ValueError("duplicate_book_token")
                        seen.add(token);m = token_map[token]
                        # The generic normalizer permits receipt-time fallback; a
                        # qualification preflight must have the native epoch-ms time.
                        native_time = raw.get("timestamp")
                        if isinstance(native_time, bool) or not isinstance(native_time, (str, int, float)):
                            raise TypeError("native_book_source_timestamp_required")
                        source_ms = float(native_time)
                        if not math.isfinite(source_ms) or not source_ms.is_integer() or source_ms < 10**12:
                            raise ValueError("native_book_epoch_milliseconds_required")
                        if source_ms > received.timestamp()*1000:
                            raise ValueError("future_native_book_source_timestamp")
                        books[token] = normalize_book(raw, m.market_id, token, received)
                    except (KeyError, TypeError, ValueError, OverflowError) as error:
                        reasons[str(error)[:100]] += 1
            except (httpx.HTTPError, ValueError, TypeError, KeyError, UnicodeError) as error:
                reasons["book_source_failure:"+type(error).__name__] += 1
        elif token_map:
            reasons["book_preflight_request_budget_exhausted"] += 1
        observed = _now();health = {}
        for raw, records in chosen:
            healthy, rejected, depth = [], Counter(), 0.
            details = []
            for m in records:
                book = books.get(m.token_id)
                if book is None or m.token_id in duplicates:
                    rejected["missing_preflight_book"] += 1;continue
                assessment = assess_book(book, observed, max_spread=.05, expected_token=m.token_id)
                details.append({"token_id": m.token_id, "outcome": m.outcome, "book_id": book.id,
                    "source_at": book.timestamp.isoformat(), "available_at": book.available_at.isoformat(),
                    "age_seconds": assessment.age_seconds, "spread": assessment.spread,
                    "healthy": assessment.healthy, "reasons": list(assessment.reasons)})
                if assessment.healthy:
                    healthy.append(m.token_id)
                    depth += min(sum(x.price*x.size for x in book.bids[:3]), sum(x.price*x.size for x in book.asks[:3]))
                else:
                    rejected.update(assessment.reasons)
            health[str(raw["id"])] = {"market_id": str(raw["id"]), "event_id": records[0].event_id,
                "preflight_eligible": bool(healthy), "healthy_tokens": healthy, "observed_top3_two_sided_depth_usd": depth,
                "rejections": dict(rejected), "book_observations": details,
                "status": "fresh_executable_book_candidate" if healthy else "metadata_only_warmup",
                "trading_authority": False}
        chosen.sort(key=lambda row: (-len(health[str(row[0]["id"])]["healthy_tokens"]),
            -health[str(row[0]["id"])]["observed_top3_two_sided_depth_usd"],
            -_nonnegative(row[0].get("liquidityNum", row[0].get("liquidity"))), str(row[0]["id"])))
        return {"schema_version": "phase19-forecast-discovery-v1", "requested_at": now.isoformat(),
            "observed_at": observed.isoformat(), "markets": [raw for raw, _m in chosen],
            "books": [b.model_dump(mode="json") for token, b in books.items() if token not in duplicates],
            "health_by_market": health, "provenance": provenance, "rejections": dict(reasons),
            "requests_used": requests, "request_limit": max_requests, "raw_response_bytes": total_bytes,
            "compatible_markets_seen": len(candidates), "candidate_limit": max_candidates,
            "selection": "exact ongoing local-day rules; native-book health then displayed depth; no forecasting price features",
            "trading_authority": False, "certification_authority": False}
    finally:
        if own:
            await client.aclose()
