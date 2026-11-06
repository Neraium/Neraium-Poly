"""Bounded, replayable public evidence acquisition. No execution or approval.

Current downloads retain current availability even when their event timestamps
are historical. A chart point is not an order book or executable quote.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data.polymarket import CLOB, DATA, GAMMA, timestamp
from neraium_poly.research.contracts import ResearchBundle, ResearchContext, ResearchEvent, ResearchPrice


def _bytes(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v),
    ).encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _array(value):
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, list):
        raise TypeError("array required")
    return value


def _optional_time(value):
    if not value:
        return None
    try:
        return timestamp(value)
    except (ValueError, TypeError, OverflowError):
        return None


class AcquisitionLimit(ValueError):
    """Acquisition stopped without weakening resource or provenance requirements."""


class HistoryPipeline:
    def __init__(
        self,
        directory: str | Path,
        *,
        client: httpx.AsyncClient | None = None,
        max_bytes: int = 100 * 1024 * 1024,
        max_requests: int = 400,
        min_interval: float = 0.1,
        clock=None,
        sleep=asyncio.sleep,
        max_market_rows: int = 500,
        offset_stride: int = 500,
    ):
        if not 1024 <= max_bytes <= 100 * 1024 * 1024 or not 1 <= max_requests <= 1000:
            raise ValueError("bounded byte and request budgets required")
        if not 1 <= max_market_rows <= 500 or not 100 <= offset_stride <= 10000 or min_interval < 0:
            raise ValueError("bounded deterministic discovery required")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.directory).free < max_bytes + 1024 * 1024 * 1024:
            raise AcquisitionLimit("insufficient free disk for bounded research")
        self.raw = self.directory / "raw"
        self.raw.mkdir(exist_ok=True)
        self.client = client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self.owns_client = client is None
        self.max_bytes, self.max_requests = max_bytes, max_requests
        self.max_market_rows, self.offset_stride = max_market_rows, offset_stride
        self.min_interval, self.clock, self.sleep = min_interval, clock or (lambda: datetime.now(UTC)), sleep
        self.requests = 0
        self.downloaded_bytes = 0
        self.archives = []
        self.errors = []
        self._existing_bytes = sum(p.stat().st_size for p in self.directory.rglob("*") if p.is_file())

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    async def _fetch(self, url: str, params: dict | None = None):
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in {
            "gamma-api.polymarket.com",
            "clob.polymarket.com",
            "data-api.polymarket.com",
            "aviationweather.gov",
        }:
            raise ValueError("only reviewed public source hosts are supported")
        for attempt in range(3):
            if self.requests >= self.max_requests:
                raise AcquisitionLimit("request budget exhausted")
            self.requests += 1
            await self.sleep(self.min_interval)
            try:
                async with self.client.stream("GET", url, params=params) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        self.downloaded_bytes += len(chunk)
                        if (
                            self._existing_bytes + self.downloaded_bytes > self.max_bytes
                            or len(body) + len(chunk) > 20 * 1024 * 1024
                        ):
                            raise AcquisitionLimit("download byte budget exhausted")
                        body.extend(chunk)
                    received = self.clock()
                    digest = _hash(bytes(body))
                    relative = f"raw/{digest}.json"
                    (self.directory / relative).write_bytes(body)
                    meta = {
                        "url": str(response.request.url),
                        "method": "GET",
                        "status": response.status_code,
                        "received_at": received.isoformat(),
                        "bytes": len(body),
                        "sha256": digest,
                        "path": relative,
                        "headers": {
                            k: response.headers[k]
                            for k in ("date", "age", "cache-control", "cf-cache-status")
                            if k in response.headers
                        },
                    }
                    self.archives.append(meta)
                    if response.status_code in (429, 503) and attempt < 2:
                        delay = float(response.headers.get("Retry-After", 2**attempt))
                        if not 0 <= delay <= 30:
                            raise AcquisitionLimit("source retry delay requires later acquisition")
                        await self.sleep(delay)
                        continue
                    response.raise_for_status()
                    return json.loads(body), meta
            except httpx.TransportError:
                if attempt == 2:
                    raise
                await self.sleep(2**attempt)
        raise AcquisitionLimit("retry budget exhausted")

    def _event(self, raw, meta, resolution, clob):
        tokens = _array(raw.get("positionIds") if raw.get("version") == "v2" else raw.get("clobTokenIds", []))
        outcomes = _array(raw.get("outcomes", []))
        if len(tokens) != 2 or len(set(tokens)) != 2 or len(outcomes) != 2:
            raise ValueError("binary outcome identity unavailable")
        yes = [i for i, value in enumerate(outcomes) if str(value).casefold() == "yes"]
        if len(yes) != 1:
            raise ValueError("unambiguous YES token required")
        index = yes[0]
        group = next(
            (str(e.get("parentEventId") or e["id"]) for e in raw.get("events", []) if e.get("id")),
            str(raw.get("eventId") or ""),
        )
        if not group or not raw.get("id") or not raw.get("question"):
            raise ValueError("market/event identity unavailable")
        received = max(
            timestamp(m["received_at"])
            for m in [meta, resolution[1] if resolution else meta, clob[1] if clob else meta]
        )
        created = _optional_time(raw.get("createdAt"))
        closed = _optional_time(raw.get("closedTime"))
        if created and created > received:
            raise ValueError("future market creation")
        verified, outcome, settled, settlement_ref = False, None, None, ""
        row, proof_meta = resolution if resolution else ({}, {})
        if (
            raw.get("closed") is True
            and row.get("condition_id") == raw.get("conditionId")
            and row.get("status") == "resolved"
            and row.get("extended_review") is False
            and row.get("was_disputed") is False
            and row.get("was_arbitrated") is not True
            and row.get("transaction_hash")
        ):
            payouts = row.get("payouts")
            if (
                row.get("market_type") == "BINARY"
                and row.get("resolution_source") == "reported"
                and payouts in ([1_000_000, 0], [0, 1_000_000])
                and all(type(v) is int for v in payouts)
            ):
                outcome, verified = int(payouts[index] == 1_000_000), True
            elif clob:
                details, _ = clob
                ctokens = details.get("tokens", [])
                # Corroborated explicit winner flags, not their displayed prices.
                matched = {str(t.get("token_id")): t for t in ctokens if isinstance(t, dict)}
                if (
                    details.get("condition_id") == raw.get("conditionId")
                    and details.get("closed") is True
                    and len(ctokens) == 2
                    and set(matched) == {str(t) for t in tokens}
                    and all(type(t.get("winner")) is bool for t in ctokens)
                    and sum(t["winner"] for t in ctokens) == 1
                    and all(
                        str(matched[str(t)]["outcome"]).casefold() == str(o).casefold()
                        for t, o in zip(tokens, outcomes, strict=True)
                    )
                ):
                    outcome, verified = int(matched[str(tokens[index])]["winner"]), True
            if verified:
                settled = _optional_time(row.get("resolved_at"))
                if settled and settled > received:
                    raise ValueError("future resolution")
                settlement_ref = proof_meta.get("path", "") + "#" + str(raw["conditionId"])
        category = raw.get("category") or next(
            (t.get("label") for e in raw.get("events", []) for t in e.get("tags", []) if t.get("label")),
            "unknown",
        )

        def numeric(*names):
            for name in names:
                if raw.get(name) is not None:
                    try:
                        value = float(raw[name])
                        return value if value >= 0 else None
                    except (TypeError, ValueError):
                        pass
            return None

        values = {
            "timestamp": created or received,
            "available_at": received,
            "source": GAMMA,
            "market_id": str(raw["id"]),
            "event_id": group,
            "token_id": str(tokens[index]),
            "question": raw["question"],
            "category": str(category),
            "created_at": created,
            "closed_at": closed,
            "resolution_rules": raw.get("description") or "",
            "resolution_source": raw.get("resolutionSource") or "",
            "outcome": outcome,
            "outcome_verified": verified,
            "settlement_at": settled,
            "settlement_ref": settlement_ref,
            "volume": numeric("volumeNum", "volume"),
            "liquidity": numeric("liquidityNum", "liquidity"),
            "availability_basis": "collected_now",
            "raw_sha256": meta["sha256"],
            "raw_ref": meta["path"] + "#" + str(raw["id"]),
        }
        return ResearchEvent(id=_hash(_bytes(values)), **values)

    async def acquire(
        self,
        max_events: int = 250,
        max_history_requests: int = 50,
        *,
        max_context_requests: int = 5,
        archive_path: str | Path | None = None,
    ) -> ResearchBundle:
        if (
            not 1 <= max_events <= 250
            or not 0 <= max_history_requests <= 250
            or not 0 <= max_context_requests <= 10
        ):
            raise ValueError("bounded evidence acquisition required")
        selected, chosen_groups = [], set()
        for page in range((self.max_market_rows + 99) // 100):
            limit = min(100, self.max_market_rows - page * 100)
            try:
                rows, meta = await self._fetch(
                    GAMMA + "/markets",
                    {
                        "closed": "true",
                        "limit": limit,
                        "offset": page * self.offset_stride,
                        "order": "closedTime",
                        "ascending": "false",
                    },
                )
            except httpx.HTTPError as exc:
                self.errors.append("discovery_page_unavailable:" + type(exc).__name__)
                break
            if not isinstance(rows, list):
                raise TypeError("invalid closed-market discovery")
            for raw in rows:
                try:
                    preliminary = self._event(raw, meta, None, None)
                except (ValueError, TypeError, KeyError):
                    self.errors.append("unsupported_market_metadata")
                    continue
                if preliminary.event_id not in chosen_groups:
                    selected.append((raw, meta, preliminary))
                    chosen_groups.add(preliminary.event_id)
                if len(selected) >= max_events:
                    break
            if len(selected) >= max_events or len(rows) < limit:
                break
        resolution_map = {}
        conditions = list(
            dict.fromkeys(str(row[0].get("conditionId", "")) for row in selected if row[0].get("conditionId"))
        )
        for start in range(0, len(conditions), 20):
            try:
                result, meta = await self._fetch(
                    DATA + "/v2/resolutions", {"condition": ",".join(conditions[start : start + 20])}
                )
                for row in result.get("data", []):
                    condition = row.get("condition_id")
                    if condition in resolution_map:
                        resolution_map[condition] = None  # Ambiguous rows cannot establish a unique label.
                    else:
                        resolution_map[condition] = (row, meta)
            except (httpx.HTTPError, ValueError) as exc:
                if isinstance(exc, AcquisitionLimit):
                    raise
                self.errors.append("resolution_lookup_failed:" + type(exc).__name__)
        events, prices = [], []
        for raw, meta, preliminary in selected:
            resolution = resolution_map.get(raw.get("conditionId"))
            clob = None
            if (
                resolution
                and resolution[0].get("payouts") is None
                and resolution[0].get("status") == "resolved"
            ):
                try:
                    clob = await self._fetch(CLOB + "/markets/" + raw["conditionId"])
                except (httpx.HTTPError, ValueError) as exc:
                    if isinstance(exc, AcquisitionLimit):
                        raise
                    self.errors.append("winner_flags_unavailable:" + type(exc).__name__)
            event = self._event(raw, meta, resolution, clob)
            events.append(event)
            if resolution and resolution[0].get("new_version_q") is True:
                self.errors.append("historical_rule_version_review_required")
        for event in events[:max_history_requests]:
            try:
                result, meta = await self._fetch(
                    DATA + "/v2/prices-history",
                    {"token_id": event.token_id, "interval": "max", "bucket_seconds": 43200, "limit": 2500},
                )
                rows = result.get("data", [])
                for row in rows:
                    at = timestamp(row["timestamp"])
                    received = timestamp(meta["received_at"])
                    if at > received:
                        raise ValueError("future historical observation")
                    boundary = min(
                        (v for v in (event.closed_at, event.settlement_at) if v is not None), default=None
                    )
                    if float(row["price"]) in (0, 1) or (boundary is not None and at >= boundary):
                        self.errors.append("terminal_or_postclose_chart_points_excluded")
                        continue
                    # Zero-resolution rows can include a final settlement payout.
                    # They remain observed chart points, never evidence of fills.
                    values = {
                        "timestamp": at,
                        "available_at": received,
                        "source": DATA + "/v2/prices-history",
                        "market_id": event.market_id,
                        "event_id": event.event_id,
                        "token_id": event.token_id,
                        "probability": float(row["price"]),
                        "availability_basis": "collected_now",
                        "raw_sha256": meta["sha256"],
                        "raw_ref": meta["path"],
                    }
                    prices.append(ResearchPrice(id=_hash(_bytes(values)), **values))
                if result.get("pagination", {}).get("has_more"):
                    self.errors.append("history_page_truncated")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                if isinstance(exc, AcquisitionLimit):
                    raise
                self.errors.append("price_history_unavailable:" + type(exc).__name__)
        context = await self._context(events, max_context_requests)
        books = self.import_books(archive_path) if archive_path else ()
        deficiencies = tuple(
            sorted(
                set(
                    self.errors
                    + [
                        "historical_orderbook_depth_not_provided_by_price_history",
                        "downloaded_now_history_not_verified_point_in_time_archive",
                        "independent_context_authenticity_and_predecision_availability_require_review",
                    ]
                )
            )
        )
        normalized = {
            "events": [e.model_dump(mode="json") for e in events],
            "prices": [p.model_dump(mode="json") for p in prices],
            "books": [b.model_dump(mode="json") for b in books],
            "context": [c.model_dump(mode="json") for c in context],
            "deficiencies": list(deficiencies),
        }
        manifest = {
            "normalized_evidence_sha256": _hash(_bytes(normalized)),
            "schema_version": "1.0",
            "created_at": self.clock().isoformat(),
            "origin": "authentic_public_api_download",
            "selection": {
                "max_events": max_events,
                "max_market_rows": self.max_market_rows,
                "offset_stride": self.offset_stride,
                "ordering": "closedTime descending; fixed sampled windows; one parent/event group",
            },
            "limits": {
                "max_bytes": self.max_bytes,
                "max_requests": self.max_requests,
                "max_history_requests": max_history_requests,
            },
            "requests": self.requests,
            "downloaded_bytes": self.downloaded_bytes,
            "raw": self.archives,
            "outcome_verification": "native explicit binary payouts or resolved lifecycle corroborated by exact CLOB winner flags; never chart prices",
            "availability_policy": "All HTTP downloads collected_now; source timestamps do not retroactively prove receipt availability",
            "deficiencies": deficiencies,
        }
        manifest_bytes = _bytes(manifest)
        now = self.clock()
        bundle = ResearchBundle(
            id=_hash(manifest_bytes),
            timestamp=now,
            available_at=now,
            source="polymarket-public-history-acquisition/v1",
            events=tuple(events),
            prices=tuple(prices),
            books=tuple(books),
            context=tuple(context),
            manifest_sha256=_hash(manifest_bytes),
            deficiencies=deficiencies,
        )
        serialized = bundle.model_dump_json(indent=2) + "\n"
        if (
            self._existing_bytes + self.downloaded_bytes + len(manifest_bytes) + len(serialized.encode())
            > self.max_bytes
        ):
            raise AcquisitionLimit("normalized evidence exceeds total dataset byte budget")
        (self.directory / "manifest.json").write_bytes(manifest_bytes)
        (self.directory / "bundle.json").write_text(serialized)
        (self.directory / "completeness.json").write_bytes(_bytes(completeness_report(bundle)))
        return bundle

    async def _context(self, events, maximum):
        context = []
        seen = set()
        for event in events:
            import re

            stations = (
                re.findall(r"\b[EK][A-Z]{3}\b", event.resolution_rules)
                if "METAR" in event.resolution_rules
                else []
            )
            if not stations or len(seen) >= maximum:
                continue
            station = stations[0]
            if station in seen:
                continue
            seen.add(station)
            try:
                rows, meta = await self._fetch(
                    "https://aviationweather.gov/api/data/metar",
                    {"ids": station, "hours": 48, "format": "json"},
                )
                if not isinstance(rows, list):
                    raise TypeError("invalid public METAR payload")
                for row in rows:
                    at = timestamp(row["obsTime"])
                    received = timestamp(meta["received_at"])
                    if at > received or row.get("icaoId") != station:
                        continue
                    values = {
                        "timestamp": at,
                        "available_at": received,
                        "source": "https://aviationweather.gov/api/data/metar",
                        "event_id": event.event_id,
                        "kind": "observed_METAR_temperature_context",
                        "value": row.get("temp"),
                        "reference": meta["path"] + "#" + str(row["obsTime"]),
                        "independent": True,
                        "availability_basis": "collected_now",
                        "raw_sha256": meta["sha256"],
                    }
                    context.append(ResearchContext(id=_hash(_bytes(values)), **values))
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                if isinstance(exc, AcquisitionLimit):
                    raise
                self.errors.append("external_context_unavailable:" + type(exc).__name__)
        return context

    def import_books(self, path: str | Path, max_books: int = 500):
        """Copy genuine archived snapshots, preserving original event/receipt time."""
        if not 1 <= max_books <= 5000:
            raise ValueError("bounded book import required")
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT payload,digest FROM events WHERE kind='OrderBookSnapshot' ORDER BY available_at,id LIMIT ?",
                (max_books,),
            ).fetchall()
        finally:
            connection.close()
        result = []
        for payload, digest in rows:
            if _hash(payload.encode()) != digest:
                raise ValueError("corrupt source book archive")
            book = OrderBookSnapshot.model_validate_json(payload)
            if book.source != CLOB:
                raise ValueError("non-exchange book source")
            result.append(book)
        artifact = _bytes([b.model_dump(mode="json") for b in result])
        if self._existing_bytes + self.downloaded_bytes + len(artifact) > self.max_bytes:
            raise AcquisitionLimit("book import exceeds byte budget")
        digest = _hash(artifact)
        relative = f"raw/{digest}.json"
        (self.directory / relative).write_bytes(artifact)
        self.downloaded_bytes += len(artifact)
        self.archives.append(
            {
                "url": "file:" + str(Path(path).resolve()),
                "method": "immutable_record_copy",
                "status": 200,
                "received_at": self.clock().isoformat(),
                "bytes": len(artifact),
                "sha256": digest,
                "path": relative,
            }
        )
        return tuple(result)


def load_bundle(path: str | Path) -> ResearchBundle:
    directory = Path(path)
    if directory.is_file():
        directory = directory.parent
    manifest_bytes = (directory / "manifest.json").read_bytes()
    bundle = ResearchBundle.model_validate_json((directory / "bundle.json").read_text())
    if _hash(manifest_bytes) != bundle.manifest_sha256:
        raise ValueError("research manifest hash mismatch")
    manifest = json.loads(manifest_bytes)
    normalized = {
        name: [record.model_dump(mode="json") for record in getattr(bundle, name)]
        for name in ("events", "prices", "books", "context")
    }
    normalized["deficiencies"] = list(bundle.deficiencies)
    if _hash(_bytes(normalized)) != manifest["normalized_evidence_sha256"]:
        raise ValueError("normalized research evidence hash mismatch")
    for item in manifest["raw"]:
        raw_path = (directory / item["path"]).resolve()
        if not raw_path.is_relative_to(directory.resolve()) or _hash(raw_path.read_bytes()) != item["sha256"]:
            raise ValueError("research raw provenance hash mismatch")
    return bundle


def completeness_report(bundle: ResearchBundle) -> dict:
    verified = {e.event_id for e in bundle.events if e.outcome_verified and e.outcome in (0, 1)}
    by_event = {e.event_id: e for e in bundle.events}
    prices_by_event = Counter(p.event_id for p in bundle.prices)
    candidate_ids = set()
    for book in bundle.books:
        for event in bundle.events:
            if (
                event.market_id != book.market_id
                or event.token_id != book.token_id
                or not event.outcome_verified
                or event.settlement_at is None
                or event.availability_basis != "verified_archive"
            ):
                continue
            if (
                not 0 <= (book.available_at - book.timestamp).total_seconds() <= 15
                or not book.complete
                or not book.bids
                or not book.asks
            ):
                continue
            if any(
                c.event_id == event.event_id
                and c.independent
                and c.availability_basis == "verified_archive"
                and c.available_at <= book.available_at
                and c.timestamp <= book.timestamp
                for c in bundle.context
            ):
                candidate_ids.add(event.event_id)
    limitations = list(bundle.deficiencies)
    if len(verified) < 200:
        limitations.append("fewer_than_200_verified_independent_parent_event_groups_in_bounded_sample")
    if len(candidate_ids) < 200:
        limitations.append("100_training_plus_100_heldout_executable_point_in_time_events_not_established")
    if not bundle.books:
        limitations.append("no_actual_historical_orderbook_snapshots")
    if not any(c.independent and c.availability_basis == "verified_archive" for c in bundle.context):
        limitations.append("no_verified_predecision_independent_context_archive")
    return {
        "events": len(bundle.events),
        "distinct_event_groups": len(by_event),
        "verified_outcome_events": len(verified),
        "historical_price_points": len(bundle.prices),
        "events_with_prices": len(prices_by_event),
        "actual_orderbook_snapshots": len(bundle.books),
        "context_observations": len(bundle.context),
        "verified_archived_context_observations": sum(
            c.independent and c.availability_basis == "verified_archive" for c in bundle.context
        ),
        "certifiable_independent_events": len(candidate_ids),
        "minimum_training_events": 100,
        "minimum_heldout_events": 100,
        "certification_split_feasible": len(candidate_ids) >= 200,
        "deficiencies": sorted(set(limitations)),
        "availability_basis_counts": dict(Counter(e.availability_basis for e in bundle.events)),
        "categories": dict(Counter(e.category for e in bundle.events)),
        "dataset_sha256": _hash(bundle.model_dump_json().encode()),
        "manifest_sha256": bundle.manifest_sha256,
        "selection_warning": "bounded convenience sample; parent/event IDs reduce known shared-event duplication, not proof of all-event statistical independence",
    }
