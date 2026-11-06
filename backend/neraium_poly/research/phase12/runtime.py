"""Persistent forward event research inside the existing paper process.

Only observed market baselines are generated automatically. Independent model
and outcome admission require verified evidence; missing evidence stays blocked.
"""

import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data import assess_book
from neraium_poly.research.phase12.admission import assess_event_proposal
from neraium_poly.research.phase12.contracts import EventEvidence, EventForecast


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class EventResearchRuntime:
    def __init__(
        self,
        directory,
        *,
        clock=None,
        dataset_path=None,
        state=None,
        interval=300,
        max_forecasts=6,
        max_bytes=64 * 1024 * 1024,
    ):
        from neraium_poly.research.phase12.ledger import EventForecastLedger
        from neraium_poly.research.phase12.relationships import EventRelationshipEngine

        self.directory = Path(directory)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.dataset_path = Path(dataset_path) if dataset_path else None
        self.interval, self.max_forecasts = interval, max_forecasts
        self.approved_outcomes = {}
        self.ledger = EventForecastLedger(
            directory,
            clock=self.clock,
            outcome_validator=self._verified_outcome,
            max_records=20000,
            max_bytes=max_bytes,
        )
        self.relationships = EventRelationshipEngine()
        state = state or {}
        anchored = state.get("ledger_head")
        if anchored:
            actual = self.ledger.verify()
            prefix = self.ledger.db.execute(
                "SELECT chain FROM journal WHERE seq=?", (anchored["records"],)
            ).fetchone()
            if actual["records"] < anchored["records"] or (
                anchored["records"] and (prefix is None or prefix[0] != anchored["head_sha256"])
            ):
                self.ledger.close()
                raise ValueError("rolled back or replaced forecast ledger")
        self.last_at = state.get("last_at")
        self.last_by_market = state.get("last_by_market", {})
        self.rejections = Counter(state.get("rejections", {}))
        self.totals = state.get("totals", {"cycles": 0, "market_baselines": 0, "proposal_evaluations": 0})
        self.resolution_attempts = state.get("resolution_attempts", {})
        self.resolution_status = state.get("resolution_status", {"attempts": 0, "verified": 0})
        self.last_error = None
        self.qualification = {"status": "unavailable", "reason": "Canonical dataset not loaded"}
        if state.get("relationships"):
            self.relationships.restore(state["relationships"])
        self.relationship_status = state.get("relationship_status", {})

    def _verified_outcome(self, outcome):
        known = self.approved_outcomes.get(outcome.id)
        return known is not None and known.model_dump(mode="json") == outcome.model_dump(mode="json")

    def _refresh_outcomes(self):
        if self.dataset_path is None or not (self.dataset_path / "manifest.json").is_file():
            return
        from neraium_poly.research.phase12.dataset import load_dataset

        dataset = load_dataset(self.dataset_path)
        self.approved_outcomes.update({o.id: o for o in dataset["outcomes"]})
        self.qualification = dataset["manifest"]
        pending = self.ledger.pending_forecasts()
        for outcome in dataset["outcomes"]:
            if any(
                (f.event_id, f.market_id, f.token_id)
                == (outcome.event_id, outcome.market_id, outcome.token_id)
                and f.timestamp < outcome.settled_at
                for f in pending
            ):
                self.ledger.record_outcome(outcome)

    def on_frame(self, frame, now):
        if (
            frame.producer_health.get("status") != "ok"
            or frame.timestamp > now
            or frame.available_at > now
            or (now - frame.available_at).total_seconds() > 15
        ):
            self.last_error = "fresh_healthy_event_frame_required"
            self.rejections[self.last_error] += 1
            return
        self.relationship_status = self.relationships.observe(frame, now)
        if self.last_at and (now - datetime.fromisoformat(self.last_at)).total_seconds() < self.interval:
            return
        self._refresh_outcomes()
        now = self.clock()  # The evidence cutoff follows proof refresh, never precedes it.
        books = {b.token_id: b for b in frame.books}
        chosen, seen = [], set()
        for market in sorted(
            frame.markets,
            key=lambda m: (m.end_time or datetime.max.replace(tzinfo=UTC), m.market_id, m.token_id),
        ):
            book = books.get(market.token_id)
            known_resolved = any(
                o.event_id == market.event_id and o.market_id == market.market_id and o.settled_at <= now
                for o in self.approved_outcomes.values()
            )
            if (
                known_resolved
                or market.market_id in seen
                or market.status != "active"
                or not market.resolution_rules
                or not market.resolution_source
                or market.available_at > now
                or market.end_time is None
                or (market.end_time - now).total_seconds() <= 300
            ):
                continue
            if not assess_book(book, now, expected_token=market.token_id, max_spread=0.05).healthy:
                continue
            previous = self.last_by_market.get(market.market_id)
            if previous and (now - datetime.fromisoformat(previous)).total_seconds() < 3600:
                continue
            seen.add(market.market_id)
            chosen.append((market, book))
            if len(chosen) >= self.max_forecasts:
                break
        for market, book in chosen:
            evidence = []
            for kind, source, timestamp, payload in (
                ("order_book", book.source, book.timestamp, {"book": book.model_dump(mode="json")}),
                (
                    "resolution_rules",
                    market.source,
                    market.timestamp,
                    {"market": market.model_dump(mode="json")},
                ),
            ):
                content = digest(payload)
                record = EventEvidence(
                    id=digest([kind, content, now.isoformat()]),
                    timestamp=timestamp,
                    available_at=now,
                    source=source,
                    event_id=market.event_id,
                    market_id=market.market_id,
                    kind=kind,
                    content_sha256=content,
                    payload=payload,
                )
                self.ledger.record_evidence(record)
                evidence.append(record)
            midpoint = (book.bids[0].price + book.asks[0].price) / 2
            forecast = EventForecast(
                id=digest(["market-baseline", market.market_id, market.token_id, now.isoformat()]),
                timestamp=now,
                available_at=now,
                source="neraium-poly/event-research/v1",
                event_id=market.event_id,
                market_id=market.market_id,
                token_id=market.token_id,
                dependency_group="unreviewed-parent:" + market.event_id,
                kind="market_baseline",
                probability=midpoint,
                market_probability=midpoint,
                evidence_cutoff=now,
                model_version="observed-midpoint-baseline-v1",
                feature_version="actual-public-book-and-rules-v1",
                dataset_sha256=digest([r.model_dump(mode="json") for r in evidence]),
                model_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                resolution_rules_sha256=hashlib.sha256(market.resolution_rules.encode()).hexdigest(),
                evidence_ids=tuple(r.id for r in evidence),
                uncertainty={
                    "type": "market_spread_not_calibrated_confidence_interval",
                    "bid": book.bids[0].price,
                    "ask": book.asks[0].price,
                    "independent_forecasting_skill": False,
                },
                horizon_seconds=(market.end_time - now).total_seconds() if market.end_time else None,
                calibration_status="market_baseline_only_not_independent",
            )
            self.ledger.record_forecast(forecast)
            proposal = assess_event_proposal(
                forecast, market, book, now=now, fee_schedule=frame.fees.get(market.token_id), enabled=False
            )
            self.rejections.update(proposal["reasons"])
            self.totals["market_baselines"] += 1
            self.totals["proposal_evaluations"] += 1
            self.last_by_market[market.market_id] = now.isoformat()
        # Bound selection history without resetting existing forecast records.
        self.last_by_market = dict(sorted(self.last_by_market.items(), key=lambda item: item[1])[-400:])
        self.last_at = now.isoformat()
        self.totals["cycles"] += 1
        self.last_error = None

    def checkpoint(self):
        return {
            "ledger_head": self.ledger.verify(),
            "resolution_attempts": self.resolution_attempts,
            "resolution_status": self.resolution_status,
            "last_at": self.last_at,
            "last_by_market": self.last_by_market,
            "rejections": dict(self.rejections),
            "totals": self.totals,
            "relationships": self.relationships.checkpoint(),
            "relationship_status": self.relationship_status,
        }

    def summary(self):
        funnel = self.qualification.get("qualification_funnel", {})
        historical = {
            **self.qualification,
            "events": funnel.get("canonical_market_propositions"),
            "chain_corroborated_exact_settlement_groups": funnel.get("corroborated_finalized_outcome_groups"),
            "qualified_training_events": funnel.get("fully_qualified_training_events"),
            "qualified_heldout_events": funnel.get("fully_qualified_heldout_events"),
        }
        relationships = {
            **self.relationship_status,
            "qualified_findings": self.relationship_status.get("statistical_findings"),
        }
        return {
            **self.ledger.summary(now=self.clock()),
            "last_evaluation_at": self.last_at,
            "last_error": self.last_error,
            "totals": dict(self.totals),
            "rejection_reasons": dict(self.rejections),
            "rejections": dict(self.rejections),
            "relationships": relationships,
            "historical_qualification": historical,
            "experimental_opportunities": 0,
            "event_order_attempts": 0,
            "resolution_collection": dict(self.resolution_status),
            "independent_models_enabled": 0,
            "certification_authority": False,
            "research_status": "market_baselines_forward_only; independent evidence blocked",
            "selection_policy": "Earliest known scheduled closes among selected active valid markets; no outcome-based selection",
        }

    async def resolve_pending(self):
        """One bounded public proof acquisition per call after a known close.

        A scheduled close only schedules a check. It never supplies a payout or
        settlement timestamp. Native status and finalized chain inclusion must
        independently agree before the immutable outcome is admitted.
        """
        from neraium_poly.research.phase12.outcome_collector import (
            acquire_verified_outcome,
            verify_collected_outcome,
        )

        now = self.clock()
        for forecast in self.ledger.pending_forecasts():
            if (
                forecast.horizon_seconds is None
                or (now - forecast.timestamp).total_seconds() < forecast.horizon_seconds
            ):
                continue
            attempted = self.resolution_attempts.get(forecast.id)
            if attempted and (now - datetime.fromisoformat(attempted)).total_seconds() < 300:
                continue
            rules = [self.ledger._evidence(i) for i in forecast.evidence_ids]
            rule = next((e for e in rules if e.kind == "resolution_rules"), None)
            if rule is None or "market" not in rule.payload:
                continue
            market = MarketSnapshot.model_validate(rule.payload["market"])
            root = self.directory / "resolution-evidence"
            root.mkdir(exist_ok=True)
            used = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
            if used + 8 * 1024**2 > 32 * 1024**2:
                self.resolution_status["last_error"] = "resolution_evidence_budget_exhausted"
                return
            self.resolution_attempts[forecast.id] = now.isoformat()
            self.resolution_attempts = dict(
                sorted(self.resolution_attempts.items(), key=lambda v: v[1])[-400:]
            )
            self.resolution_status["attempts"] += 1
            self.resolution_status["last_checked_at"] = now.isoformat()
            output = root / (
                now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + hashlib.sha256(forecast.id.encode()).hexdigest()[:12]
            )
            try:
                outcome = await acquire_verified_outcome(forecast, market, output)
                if outcome is None:
                    self.resolution_status["last_error"] = (
                        "native_or_finalized_resolution_evidence_unavailable"
                    )
                    return
                accepted = await asyncio.to_thread(verify_collected_outcome, outcome, market, forecast, root)
                if accepted is not True:
                    self.resolution_status["last_error"] = "independent_resolution_replay_failed"
                    return
                self.approved_outcomes[outcome.id] = outcome
                self.ledger.record_outcome(outcome)
                self.resolution_status["verified"] += 1
                self.resolution_status["last_error"] = None
            except Exception as error:  # noqa: BLE001 - incomplete verification remains unscored
                self.resolution_status["last_error"] = f"{type(error).__name__}:{str(error)[:120]}"
            return

    def close(self):
        self.ledger.close()
