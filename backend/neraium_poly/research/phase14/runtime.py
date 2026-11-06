"""Bounded universal evidence research inside the existing paper process.

Discovery, evidence sources, models and account authority are separate. Disk
exhaustion withholds durable collection; cached classifications are labeled as
such. Existing sports records remain owned by the Phase13 journal.
"""

import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.data import assess_book
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase14.contracts import DomainForecast, DomainMarket
from neraium_poly.research.phase14.ledger import UniversalForecastLedger

DOMAINS = (
    "weather",
    "crypto",
    "finance",
    "economics",
    "politics",
    "sports",
    "esports",
    "technology",
    "science",
    "geopolitics",
    "entertainment",
    "other",
)
CAPABILITIES = {
    "weather": "observations implemented; qualified predictive distribution unavailable",
    "crypto": "closed-candle evidence implemented; terminal time convention requires review",
    "economics": "official calendar context implemented; vintage/model evidence insufficient",
    "sports": "legacy NFL ternary research preserved; no trading authority",
    "finance": "exact reference/settlement interpretation required; no general price model",
}


def adapter(domain):
    if domain == "weather":
        from neraium_poly.research.phase14.weather import collect_weather, forecast_weather, map_weather

        return map_weather, collect_weather, forecast_weather
    if domain == "crypto":
        from neraium_poly.research.phase14.finance import collect_financial, forecast_financial, map_financial

        return map_financial, collect_financial, forecast_financial
    if domain == "economics":
        from neraium_poly.research.phase14.economics import collect_economic, forecast_economic, map_economic

        return map_economic, collect_economic, forecast_economic
    return None


class DomainResearchRuntime:
    def __init__(self, directory, *, clock=None, state=None, interval=1800):
        if not 300 <= interval <= 86400:
            raise ValueError("bounded domain source refresh required")
        self.directory = Path(directory)
        self.clock = clock or (lambda: datetime.now(UTC))
        state = state or {}
        self.interval = interval
        from neraium_poly.research.phase14.models import research_registry

        self.registry = research_registry()
        self.ledger = None
        self.outcome_collector = None
        self.anchor = state.get("anchor")
        self.last_refresh = state.get("last_refresh")
        self.rejections = Counter(state.get("rejections", {}))
        self.discovered = {
            m.market_id: m for m in (DomainMarket.model_validate(v) for v in state.get("discovered", []))
        }
        self.observed = {}
        self.last_frame_at = None
        self.source_status = "not_observed"
        self.last_error = None
        self.source_reports = state.get("source_reports", {})
        self.latest_evidence = {}
        self.last_books = {}
        self.market_snapshots = {}
        self.book_metrics = {}
        self.structural = set()
        self.totals = {
            "cycles": 0,
            "source_attempts": 0,
            "source_successes": 0,
            "forecasts": 0,
            **state.get("totals", {}),
        }
        self.discovery_status = state.get("discovery_status", {})
        self.outcome_state = state.get("outcomes", {})
        self.relationship_state = state.get("relationships")
        self.relationships = None

    def _storage_ready(self):
        parent = self.directory if self.directory.exists() else self.directory.parent
        return parent.exists() and shutil.disk_usage(parent).free >= 8 * 1024**3

    def _open(self):
        if self.ledger is None:
            if not self._storage_ready():
                raise ValueError("domain_durable_storage_below_8GiB_floor")
            self.ledger = UniversalForecastLedger(
                self.directory, clock=self.clock, anchor=self.anchor, forecast_validator=self._replay_forecast
            )
        if self.outcome_collector is None:
            from neraium_poly.research.phase14.outcomes import DomainOutcomeCollector

            self.outcome_collector = DomainOutcomeCollector(
                self.ledger, clock=self.clock, state=self.outcome_state
            )
        if self.relationships is None:
            from neraium_poly.research.phase14.relationships import UniversalRelationships

            candidate = UniversalRelationships()
            if self.relationship_state:
                candidate.restore(self.relationship_state)
            self.relationships = candidate

    def _reject(self, reason):
        reason = str(reason)[:160]
        if reason not in self.rejections and len(self.rejections) >= 128:
            reason = "other_bounded_rejection"
        self.rejections[reason] += 1

    def on_frame(self, frame, now):
        from neraium_poly.research.phase14.discovery import classify_snapshot

        self.last_frame_at = frame.timestamp.isoformat()
        healthy = (
            frame.producer_health.get("status") == "ok"
            and frame.available_at <= now
            and frame.timestamp <= now
            and (now - frame.available_at).total_seconds() <= 15
        )
        self.source_status = "fresh_public_frame" if healthy else "degraded_cached_universe"
        self.last_books = {b.token_id: b for b in frame.books} if healthy else {}
        self.observed, self.market_snapshots, self.book_metrics = {}, {}, {}
        self.structural = set()
        for m in frame.markets[:1000]:
            descriptor = classify_snapshot(m, now=now)
            self.observed.setdefault(m.market_id, self.discovered.get(m.market_id, descriptor))
            current = self.observed[m.market_id]
            if m.token_id not in current.token_ids:
                tokens = tuple(sorted(set(current.token_ids) | {m.token_id}))
                self.observed[m.market_id] = current.model_copy(
                    update={
                        "id": content_sha256(["domain-frame-market-v1", m.market_id, tokens, current.domain]),
                        "token_ids": tokens,
                    }
                )
            self.market_snapshots[m.token_id] = m
            api = adapter(descriptor.domain)
            if api is not None:
                try:
                    if api[0](m, now=now).compatible:
                        self.structural.add(m.market_id)
                except ValueError:
                    pass

            book = self.last_books.get(m.token_id)
            health = assess_book(book, now, expected_token=m.token_id, max_spread=0.05)
            if health.healthy:
                self.book_metrics.setdefault(
                    m.market_id,
                    {
                        "fresh_tokens": 0,
                        "spread": book.asks[0].price - book.bids[0].price,
                        "bid_depth_shares": sum(x.size for x in book.bids),
                        "ask_depth_shares": sum(x.size for x in book.asks),
                    },
                )["fresh_tokens"] += 1
        self.totals["cycles"] += 1
        if not healthy:
            self._reject("fresh_healthy_public_frame_required_for_domain_forecasts")
            return
        if not self._storage_ready():
            self.last_error = "domain_durable_storage_below_8GiB_floor"
            return
        self._open()
        for m in list(self.market_snapshots.values())[:1000]:
            descriptor = self.observed[m.market_id]
            api = adapter(descriptor.domain)
            evidence = self.latest_evidence.get(descriptor.domain)
            if api is None or not evidence:
                continue
            try:
                c = api[0](m, now=now)
                result = self.registry.models[c.domain].forecast(c, evidence, cutoff=now)
                if (
                    not c.compatible
                    or c.review_required
                    or result.get("status") not in {"research_estimate", "qualified"}
                    or result.get("probability") is None
                ):
                    for reason in result.get(
                        "reasons", c.reasons or ("independent_domain_probability_unavailable",)
                    ):
                        self._reject(reason)
                    continue
                book = self.last_books.get(m.token_id)
                if book is None:
                    raise ValueError("missing_current_domain_order_book")
                existing = self.ledger.forecasts()
                if any(
                    f.market_id == m.market_id
                    and f.model_sha256 == result["model_sha256"]
                    and f.timestamp.date() == now.date()
                    for f in existing
                ):
                    continue
                f = DomainForecast(
                    id=content_sha256(
                        [
                            "domain-forecast-v1",
                            m.market_id,
                            m.token_id,
                            result["model_sha256"],
                            now.isoformat(),
                        ]
                    ),
                    timestamp=now,
                    available_at=now,
                    source="neraium-poly/universal-research/v1",
                    domain=c.domain,
                    event_id=m.event_id,
                    market_id=m.market_id,
                    token_id=m.token_id,
                    contract_type=c.contract_type,
                    probability_semantics=c.probability_semantics,
                    probability=result["probability"],
                    evidence_cutoff=now,
                    model_version=result["model_version"],
                    model_sha256=result["model_sha256"],
                    feature_version=result["feature_version"],
                    dataset_sha256=result["dataset_sha256"],
                    rules_sha256=c.rules_sha256,
                    evidence_ids=tuple(e.id for e in evidence),
                    uncertainty=result["uncertainty"],
                    calibration_status=result.get("calibration_status", "unvalidated_research"),
                    independent_of_polymarket=True,
                    dependency_group="unreviewed-parent:" + m.event_id,
                    contemporaneous_market={
                        "book": book.model_dump(mode="json"),
                        "contract": c.model_dump(mode="json"),
                        "market": m.model_dump(mode="json"),
                    },
                )
                if self.ledger.record_forecast(f, contract=c, market=m, book=book):
                    self.totals["forecasts"] += 1
            except Exception as error:  # noqa: BLE001 - qualification failure never grants execution authority
                self._reject(f"{type(error).__name__}:{str(error)[:120]}")

    def _replay_forecast(self, f, c, market, evidence):
        api = adapter(f.domain)
        if api is None:
            return False
        try:
            mapped = api[0](market, now=f.timestamp)
            if mapped.model_dump(mode="json") != c.model_dump(mode="json"):
                return False
            replay = self.registry.models[f.domain].forecast(mapped, evidence, cutoff=f.evidence_cutoff)
            return (
                replay.get("status") in {"research_estimate", "qualified"}
                and replay.get("probability") == f.probability
                and replay.get("model_sha256") == f.model_sha256
                and replay.get("dataset_sha256") == f.dataset_sha256
                and replay.get("feature_version") == f.feature_version
                and replay.get("uncertainty") == f.uncertainty
                and replay.get("model_version") == f.model_version
                and replay.get("calibration_status", "unvalidated_research") == f.calibration_status
            )
        except Exception:  # noqa: BLE001 - model replay denies by default
            return False

    async def refresh(self):
        now = self.clock()
        if (
            self.last_refresh
            and (now - datetime.fromisoformat(self.last_refresh)).total_seconds() < self.interval
        ):
            return
        if not self._storage_ready():
            self.last_error = "domain_durable_storage_below_8GiB_floor"
            return
        self._open()
        from neraium_poly.research.phase14.discovery import DomainDiscovery

        self.last_refresh = now.isoformat()
        try:
            discovery = DomainDiscovery()
            try:
                result = await discovery.discover()
            finally:
                await discovery.close()
            self.discovered = {m.market_id: m for m in result["markets"]}
            self.discovery_status = result["report"]
            # One contract/source per supported domain per refresh, bounded by
            # existing monitored markets. Discovery does not widen order authority.
            seen = set()
            for m in list(self.market_snapshots.values())[:1000]:
                descriptor = self.discovered.get(m.market_id, self.observed.get(m.market_id))
                if descriptor is None or descriptor.domain in seen:
                    continue
                api = adapter(descriptor.domain)
                if api is None:
                    continue
                try:
                    c = api[0](m, now=self.clock())
                    if not c.parameters:
                        continue
                    self.totals["source_attempts"] += 1
                    evidence = await api[1](c, clock=self.clock)
                    for e in evidence:
                        self.ledger.record_evidence(e)
                    self.latest_evidence[descriptor.domain] = evidence
                    self.source_reports[descriptor.domain] = {
                        "status": "durably_ingested_research_evidence",
                        "retrieved_at": max(e.retrieved_at for e in evidence).isoformat(),
                        "evidence_ids": [e.id for e in evidence],
                    }
                    self.totals["source_successes"] += 1
                    seen.add(descriptor.domain)
                except Exception as error:  # noqa: BLE001 - unsupported evidence must remain explicit
                    self._reject(f"{descriptor.domain}:{type(error).__name__}:{str(error)[:100]}")
            self.last_error = None
        except Exception as error:  # noqa: BLE001 - preserve prior observations, no synthetic fallback
            self.last_error = f"{type(error).__name__}:{str(error)[:160]}"

    async def resolve_pending(self):
        if self.ledger is not None and self._storage_ready() and self.outcome_collector is not None:
            await self.outcome_collector.check_pending()

    def checkpoint(self):
        return {
            "anchor": self.ledger.verify() if self.ledger else self.anchor,
            "outcomes": self.outcome_collector.state if self.outcome_collector else self.outcome_state,
            "last_refresh": self.last_refresh,
            "rejections": dict(self.rejections),
            "totals": dict(self.totals),
            "source_reports": self.source_reports,
            "discovery_status": self.discovery_status,
            "discovered": [m.model_dump(mode="json") for m in list(self.discovered.values())[:200]],
            "relationships": self.relationships.checkpoint()
            if self.relationships
            else self.relationship_state,
        }

    def summary(self, *, legacy_sports=None):
        groups = {
            d: {
                "monitored_markets": 0,
                "fresh_markets": 0,
                "structurally_supported_markets": 0,
                "independent_forecasts": 0,
                "pending": 0,
                "resolved": 0,
                "model_versions": [],
                "capability": CAPABILITIES.get(
                    d, "evidence/interpretation contracts only; human review required"
                ),
            }
            for d in DOMAINS
        }
        for m in self.observed.values():
            row = groups[m.domain]
            row["monitored_markets"] += 1
            row["structurally_supported_markets"] += int(m.market_id in self.structural)
            row["fresh_markets"] += int(m.market_id in self.book_metrics)
        journal = (
            self.ledger.summary()
            if self.ledger
            else {"forecasts": 0, "outcomes": 0, "evidence_records": 0, "domains": {}}
        )
        previous_store = self.anchor is not None or (self.directory / "forecasts.sqlite").exists()
        if self.ledger is None and previous_store:
            journal.update(
                forecasts=None,
                outcomes=None,
                evidence_records=None,
                reason="Prior domain journal exists; counts withheld until verified recovery",
            )
            for row in groups.values():
                row.update(independent_forecasts=None, pending=None, resolved=None)
        for d, v in journal["domains"].items():
            groups[d].update(
                independent_forecasts=v["forecasts"],
                pending=v["pending"],
                resolved=v["resolved"],
                model_versions=v["model_versions"],
            )
        if self.last_frame_at is None:
            for row in groups.values():
                row.update(monitored_markets=None, fresh_markets=None, structurally_supported_markets=None)
        if legacy_sports is None:
            groups["sports"].update(
                independent_forecasts=None,
                pending=None,
                resolved=None,
                forecast_scope="Legacy sports journal unavailable; new domain journal counted separately",
            )
        if legacy_sports is not None:
            groups["sports"].update(
                independent_forecasts=legacy_sports.get("ternary_research_forecasts"),
                pending=legacy_sports.get("ternary_pending"),
                resolved=legacy_sports.get("ternary_resolved"),
                model_versions=legacy_sports.get("model_versions", []),
                forecast_scope="Read-only Phase13 ternary journal; no duplicated records",
            )
        return {
            "schema_version": "1.0",
            "status": "storage_blocked" if not self._storage_ready() else "research_only",
            "market_source_status": self.source_status,
            "last_frame_at": self.last_frame_at,
            "last_error": self.last_error,
            "markets_monitored": len(self.observed) if self.last_frame_at is not None else None,
            "domains": groups,
            "discovered_markets": len(self.discovered),
            "discovery": self.discovery_status,
            "source_reports": self.source_reports,
            "model_registry": self.registry.status(),
            "totals": dict(self.totals),
            "rejections": dict(self.rejections),
            "ledger": journal,
            "book_metrics": self.book_metrics,
            "relationships": self.relationships.summary()
            if self.relationships
            else {"qualified_findings": 0, "reason": "No reviewed aligned cross-domain evidence"},
            "experimental_opportunities": 0,
            "event_order_attempts": 0,
            "outcome_collection": self.outcome_collector.state
            if self.outcome_collector
            else {**self.outcome_state, "status": "not_active; storage/provenance gates"},
            "trading_authority": False,
            "certification_authority": False,
            "scores": {
                "brier": None,
                "log_loss": None,
                "confidence_interval": None,
                "reason": "No reviewed independent resolved domain cohort",
            },
            "counter_scope": "market counts current cached/fresh frame; totals/rejections cumulative; forecasts durable journal",
        }

    def close(self):
        if self.outcome_collector:
            self.outcome_collector.close()
        if self.ledger:
            self.ledger.close()
