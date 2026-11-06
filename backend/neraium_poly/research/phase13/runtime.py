"""Bounded external sports research attached to the Phase12 immutable ledger.

The adapter has no account, broker or strategy-approval reference. Its independent
forecast callback replays raw source parsing, deterministic event mapping and the
external-only model before any append. Research admission grants no trading power.
"""

import asyncio
import hashlib
import json
import shutil
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase12.admission import assess_event_proposal
from neraium_poly.research.phase12.contracts import (
    EventEvidence,
    EventForecast,
    SettlementProofReference,
    VerifiedEventOutcome,
)
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.contracts import SportsGame, SportsMapping, SportsPrediction


class TernarySportsForecast(BaseModel):
    """Explicit research estimand: W/T/L distribution, not binary payout probability."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["independent_ternary_research"]
    timestamp: datetime
    evidence_cutoff: datetime
    mapping: SportsMapping
    prediction: SportsPrediction
    market: MarketSnapshot
    book: OrderBookSnapshot
    snapshot: str
    source_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_expected_payout_baseline: float = Field(gt=0, lt=1)
    market_win_probability: None = None
    baseline_comparison: str
    dependency_group: str
    independence_reviewed: Literal[False] = False
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        mapping, prediction, market, book = self.mapping, self.prediction, self.market, self.book
        if (
            self.timestamp.tzinfo is None
            or self.evidence_cutoff != self.timestamp
            or prediction.cutoff != self.timestamp
            or mapping.event_start.tzinfo is None
            or self.timestamp >= mapping.event_start
        ):
            raise ValueError("prospective aware sports cutoff required")
        if hashlib.sha256(market.resolution_rules.encode()).hexdigest() != mapping.rules_sha256:
            raise ValueError("original sports resolution rules required")
        if mapping.league != "NFL" or (mapping.game_id, mapping.selected_team_id) != (
            prediction.game_id,
            prediction.selected_team_id,
        ):
            raise ValueError("NFL ternary prediction mapping required")
        if (mapping.event_id, mapping.market_id, mapping.token_id) != (
            market.event_id,
            market.market_id,
            market.token_id,
        ):
            raise ValueError("ternary market identity mismatch")
        if (
            book.source not in PUBLIC_BOOK_SOURCES
            or book.exchange != "polymarket"
            or (book.market_id, book.token_id) != (market.market_id, market.token_id)
            or not assess_book(book, self.timestamp, max_spread=0.05).healthy
        ):
            raise ValueError("authentic contemporaneous ternary market baseline required")
        if abs(self.market_expected_payout_baseline - (book.bids[0].price + book.asks[0].price) / 2) > 1e-12:
            raise ValueError("ternary market baseline differs from original quote")
        probabilities = prediction.uncertainty.get("outcome_probabilities", {})
        if (
            set(probabilities) != {"win", "tie", "loss"}
            or any(not isinstance(p, (int, float)) or not 0 < p < 1 for p in probabilities.values())
            or abs(sum(probabilities.values()) - 1) > 1e-10
        ):
            raise ValueError("positive normalized ternary probabilities required")
        if (
            abs(prediction.probability - probabilities["win"]) > 1e-12
            or abs(
                prediction.uncertainty.get("expected_payout", -1)
                - probabilities["win"]
                - 0.5 * probabilities["tie"]
            )
            > 1e-12
        ):
            raise ValueError("win probability and expected payout must remain distinct")
        relative = Path(self.snapshot)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) != 2
            or relative.parts[0] != "sources"
        ):
            raise ValueError("confined immutable sports snapshot required")
        return self


class TernarySportsOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    forecast_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    timestamp: datetime
    sports_result: SportsGame
    current_source_snapshot: str
    exchange_outcome: VerifiedEventOutcome
    corroboration: dict
    descriptive_scores: dict
    independence_reviewed: Literal[False] = False
    trading_authority: Literal[False] = False

    @model_validator(mode="after")
    def verified_shape(self):
        if (
            self.timestamp.tzinfo is None
            or self.sports_result.status != "final"
            or self.sports_result.available_at > self.timestamp
            or self.exchange_outcome.available_at > self.timestamp
            or self.corroboration.get("accepted") is not True
        ):
            raise ValueError("causal corroborated sports outcome required")
        return self


class SportsSettlementReference(SettlementProofReference):
    """Original sports journal proof reference; no binary probability assertion."""


class SportsForecastJournal:
    """Append-only ternary research records, isolated from binary forecasts/accounts."""

    def __init__(self, directory, *, anchor=None, max_bytes=16 * 1024**2):
        self.directory, self.max_bytes = Path(directory), max_bytes
        self._lock = RLock()
        self.path = self.directory / "prospective.sqlite"
        for p in self.directory.glob("prospective.sqlite*"):
            if p.is_symlink() or p.stat().st_nlink != 1:
                raise ValueError("sports journal aliases forbidden")
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS records(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,
              id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,digest TEXT NOT NULL,
              previous TEXT,chain TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON records
              BEGIN SELECT RAISE(ABORT,'sports journal append only'); END;
            CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON records
              BEGIN SELECT RAISE(ABORT,'sports journal append only'); END;
            """)
            actual = self.verify()
            if anchor:
                prior = self.db.execute(
                    "SELECT chain FROM records WHERE seq=?", (anchor["records"],)
                ).fetchone()
                if actual["records"] < anchor["records"] or (
                    anchor["records"] and (prior is None or prior[0] != anchor["head_sha256"])
                ):
                    raise ValueError("sports forecast journal rollback detected")
        except BaseException:
            self.db.close()
            raise

    def verify(self):
        with self._lock:
            return self._verify()

    def _verify(self):
        previous, count = None, 0
        for row in self.db.execute("SELECT * FROM records ORDER BY seq"):
            count += 1
            if (
                count > 10000
                or content_sha256(json.loads(row["payload"])) != row["digest"]
                or row["previous"] != previous
                or row["chain"] != content_sha256([previous, row["kind"], row["id"], row["digest"]])
            ):
                raise ValueError("corrupt sports forecast journal")
            payload = self._typed(row["kind"], json.loads(row["payload"])).model_dump(mode="json")
            expected_id = payload["id"] if row["kind"] == "forecast" else "outcome:" + payload["forecast_id"]
            if expected_id != row["id"]:
                raise ValueError("sports journal payload identity mismatch")
            previous = row["chain"]
        return {"records": count, "head_sha256": previous, "integrity": "verified"}

    def records(self, kind):
        return [
            json.loads(r[0])
            for r in self.db.execute("SELECT payload FROM records WHERE kind=? ORDER BY seq", (kind,))
        ]

    def append(self, kind, identity, payload):
        with self._lock:
            return self._append(kind, identity, payload)

    @staticmethod
    def _typed(kind, payload):
        if kind == "forecast":
            return TernarySportsForecast.model_validate(payload)
        if kind == "outcome":
            return TernarySportsOutcome.model_validate(payload)
        raise ValueError("typed sports forecast or outcome required")

    def _append(self, kind, identity, payload):
        payload = self._typed(kind, payload).model_dump(mode="json")
        expected_id = payload["id"] if kind == "forecast" else "outcome:" + payload["forecast_id"]
        if identity != expected_id:
            raise ValueError("sports journal payload identity mismatch")
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if kind not in {"forecast", "outcome"} or len(text.encode()) > 128 * 1024:
            raise ValueError("bounded typed sports record required")
        old = self.db.execute("SELECT kind,payload FROM records WHERE id=?", (identity,)).fetchone()
        if old:
            if tuple(old) != (kind, text):
                raise ValueError("immutable sports record collision")
            return False
        used = sum(p.stat().st_size for p in self.directory.glob("prospective.sqlite*"))
        if (
            used + len(text.encode()) > self.max_bytes
            or self.db.execute("SELECT COUNT(*) FROM records").fetchone()[0] >= 10000
        ):
            raise ValueError("sports forecast journal budget exhausted")
        if shutil.disk_usage(self.directory).free < 8 * 1024**3:
            raise ValueError("sports forecast free-disk floor")
        prev = self.db.execute("SELECT chain FROM records ORDER BY seq DESC LIMIT 1").fetchone()
        previous = prev[0] if prev else None
        digest = content_sha256(payload)
        self.db.execute(
            "INSERT INTO records(kind,id,payload,digest,previous,chain) VALUES(?,?,?,?,?,?)",
            (kind, identity, text, digest, previous, content_sha256([previous, kind, identity, digest])),
        )
        return True

    def close(self):
        self.db.close()


class SportsResearchRuntime:
    """Research-only coordinator; repeated forecasts never imply independence.

    Existing ledger callbacks must be unset. Do not replace another reviewer's
    authority. External snapshots are immutable and stop at the archive budget;
    evidence is never deleted to keep the producer running.
    """

    def __init__(
        self,
        ledger,
        directory,
        *,
        clock=None,
        state=None,
        interval=43200,
        max_bytes=64 * 1024**2,
        max_forecasts=2,
    ):
        self.ledger, self.directory = ledger, Path(directory)
        self.clock = clock or (lambda: datetime.now(UTC))
        if interval < 300 or not 1024**2 <= max_bytes <= 64 * 1024**2 or not 1 <= max_forecasts <= 6:
            raise ValueError("bounded sports research configuration required")
        if ledger.independent_forecast_validator is not None:
            raise ValueError("cannot replace an existing independent forecast reviewer")
        self.interval, self.max_bytes, self.max_forecasts = interval, max_bytes, max_forecasts
        if self.directory.is_symlink():
            raise ValueError("sports research aliases forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._safe_tree()
        state = state or {}
        self.journal = SportsForecastJournal(self.directory, anchor=state.get("journal_head"))
        try:
            self.last_attempt = state.get("last_attempt")
            self.last_success = state.get("last_success")
            self.snapshot = state.get("snapshot")
            self.last_error = state.get("last_error")
            self.rejections = Counter(state.get("rejections", {}))
            self.totals = {
                "refreshes": 0,
                "markets_considered": 0,
                "mapped": 0,
                "independent_forecasts": 0,
                "proposal_evaluations": 0,
                **state.get("totals", {}),
            }
            self.outcome_status = state.get("outcome_status", {"checks": 0, "corroborated": 0})
            self.result_attempts = state.get("result_attempts", {})
            self._approved_result_hashes = set()
            self._rejected_result_hashes = set()
            from neraium_poly.research.phase13.relationships import SportsRelationshipResearch

            self.relationships = SportsRelationshipResearch()
            if state.get("relationships"):
                self.relationships.restore(state["relationships"])
            self.relationship_status = state.get("relationship_status", {})
            self.latest_candidates = []
            self.last_eligible_games = []
            self.data = None
            self._refresh_lock = asyncio.Lock()
            if self.snapshot:
                try:
                    self.data = self._load(self.snapshot)
                except Exception as error:  # noqa: BLE001 - preserve old evidence and withhold research
                    self.last_error = f"snapshot_recovery:{type(error).__name__}:{str(error)[:120]}"
            self.ledger.independent_forecast_validator = self.validate_forecast
        except BaseException:
            self.journal.close()
            raise

    def _reject(self, reason):
        key = reason if reason in self.rejections or len(self.rejections) < 128 else "other_bounded_reason"
        self.rejections[key] += 1

    def _safe_tree(self):
        for index, p in enumerate(self.directory.rglob("*")):
            if index >= 256:
                raise ValueError("sports source file-count budget exceeded")
            if p.is_symlink() or (p.is_file() and p.stat().st_nlink != 1):
                raise ValueError("sports source aliases forbidden")

    def _path(self, relative):
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or len(p.parts) != 2 or p.parts[0] != "sources":
            raise ValueError("sports snapshot outside confined source root")
        candidate = self.directory / p
        if not candidate.is_dir() or candidate.is_symlink():
            raise ValueError("sports snapshot unavailable")
        self._safe_tree()
        return candidate

    def _load(self, relative):
        from neraium_poly.research.phase13.sources import load_sports

        path = self._path(relative)
        used = sum(p.stat().st_size for p in self.directory.rglob("*") if p.is_file())
        if used > self.max_bytes:
            raise ValueError("sports evidence budget exceeded")
        data = load_sports(path)
        if not data.get("artifacts") or any(a.quality != "qualified" for a in data["artifacts"]):
            raise ValueError("qualified source artifacts required")
        return data

    @staticmethod
    def _dataset_identity(data):
        return content_sha256(
            {
                "artifacts": [a.model_dump(mode="json") for a in data["artifacts"]],
                "games": [g.model_dump(mode="json") for g in data["games"]],
            }
        )

    async def refresh(self):
        """Bounded licensed source acquisition. No source means no independent output."""
        from neraium_poly.research.phase13.sources import collect_sports

        async with self._refresh_lock:
            now = self.clock()
            if (
                self.last_attempt
                and (now - datetime.fromisoformat(self.last_attempt)).total_seconds()
                < (min(300, self.interval) if self.last_error else self.interval)
            ):
                return
            self.last_attempt = now.isoformat()
            self.totals["refreshes"] += 1
            try:
                self._safe_tree()
                used = sum(p.stat().st_size for p in self.directory.rglob("*") if p.is_file())
                # The provider enforces a 12MiB per-acquisition ceiling; reserve
                # that amount before creating a new immutable snapshot.
                if used + 12 * 1024**2 > self.max_bytes:
                    raise ValueError("sports_evidence_budget_exhausted")
                if shutil.disk_usage(self.directory).free < 8 * 1024**3:
                    raise ValueError("sports_free_disk_floor_reached")
                relative = "sources/" + now.strftime("%Y%m%dT%H%M%S%fZ")
                destination = self.directory / relative
                destination.mkdir(parents=True, exist_ok=False)
                await collect_sports(destination, clock=self.clock, leagues=("NFL",))
                data = await asyncio.to_thread(self._load, relative)
                if any(a.available_at > self.clock() for a in data["artifacts"]):
                    raise ValueError("future external availability")
                self.snapshot, self.data = relative, data
                self._approved_result_hashes.clear()
                self._rejected_result_hashes.clear()
                self.last_success, self.last_error = self.clock().isoformat(), None
            except Exception as error:  # noqa: BLE001 - missing evidence never triggers fallback data
                self.last_error = f"{type(error).__name__}:{str(error)[:160]}"
                self._reject("external_source_refresh_failed")

    def _market_rules(self, forecast, evidence):
        rules = [e for e in evidence if e.kind == "resolution_rules"]
        if len(rules) != 1:
            raise ValueError("one original sports market rule record required")
        market = MarketSnapshot.model_validate(rules[0].payload["market"])
        if (market.event_id, market.market_id, market.token_id) != (
            forecast.event_id,
            forecast.market_id,
            forecast.token_id,
        ):
            raise ValueError("sports market mapping mismatch")
        return market

    def validate_forecast(self, forecast, evidence):
        """Never trusts an `independent` flag: replay complete external derivation."""
        from neraium_poly.research.phase13.mapping import map_market
        from neraium_poly.research.phase13.models import predict_game

        try:
            context = [e for e in evidence if e.kind == "external_context"]
            if len(context) != 1 or context[0].payload.get("type") != "qualified_sports_forecast_v1":
                return False
            item = context[0]
            if not item.independent_of_market_price:
                return False
            data = self._load(item.payload["snapshot"])
            if self._dataset_identity(data) != item.payload["source_dataset_sha256"]:
                return False
            if any(a.available_at > forecast.evidence_cutoff for a in data["artifacts"]):
                return False
            if item.available_at < max(a.available_at for a in data["artifacts"]):
                return False
            market = self._market_rules(forecast, evidence)
            mapping = map_market(market, data["games"], now=forecast.evidence_cutoff)
            if mapping.model_dump(mode="json") != item.payload["mapping"]:
                return False
            target = self._target(data, mapping)
            prediction = predict_game(
                data["games"], target, mapping.selected_team_id, forecast.evidence_cutoff
            )
            if prediction.model_dump(mode="json") != item.payload["prediction"]:
                return False
            exact = {
                "probability": prediction.probability,
                "lower_probability": prediction.lower_probability,
                "upper_probability": prediction.upper_probability,
                "model_version": prediction.model_version,
                "model_sha256": prediction.model_sha256,
                "feature_version": prediction.feature_version,
                "dataset_sha256": prediction.dataset_sha256,
                "calibration_status": prediction.calibration_status,
                "uncertainty": prediction.uncertainty,
                "resolution_rules_sha256": mapping.rules_sha256,
                "horizon_seconds": (mapping.event_start - forecast.timestamp).total_seconds(),
            }
            return (
                forecast.kind == "independent_model"
                and forecast.timestamp == forecast.evidence_cutoff == prediction.cutoff
                and forecast.timestamp < mapping.event_start
                and not forecast.independence_reviewed
                and all(getattr(forecast, k) == v for k, v in exact.items())
            )
        except Exception:  # noqa: BLE001 - invalid source/mapping/model replay denies admission
            return False

    @staticmethod
    def _target(data, mapping):
        matches = [
            g for g in data["games"] if g.game_id == mapping.game_id and g.provider == mapping.provider
        ]
        if len(matches) != 1:
            raise ValueError("unique external event required")
        return matches[0]

    def _existing(self):
        # Durable deduplication derives from the append-only ledger, so process
        # crashes between append and coordinator checkpoint cannot duplicate it.
        binary = {
            (f.market_id, f.model_sha256, f.timestamp.date())
            for f in self.ledger.forecasts()
            if f.kind == "independent_model"
        }
        return binary | {
            (
                f["market"]["market_id"],
                f["prediction"]["model_sha256"],
                datetime.fromisoformat(f["timestamp"]).date(),
            )
            for f in self.journal.records("forecast")
        }

    def on_frame(self, frame, now):
        from neraium_poly.research.phase13.mapping import map_market
        from neraium_poly.research.phase13.models import predict_game

        if (
            frame.producer_health.get("status") != "ok"
            or frame.available_at > now
            or frame.timestamp > now
            or (now - frame.available_at).total_seconds() > 15
        ):
            self._reject("fresh_healthy_sports_frame_required")
            return
        if self.data is None or not self.snapshot:
            self._reject("qualified_external_sports_dataset_unavailable")
            return
        if any((now - a.retrieved_at).total_seconds() > 2 * self.interval for a in self.data["artifacts"]):
            self._reject("external_sports_snapshot_stale")
            return
        books = {b.token_id: b for b in frame.books}
        existing = self._existing()
        parents = {f.event_id: f.dependency_group for f in self.ledger.forecasts()}
        created, self.latest_candidates, self.last_eligible_games = 0, [], []
        for market in frame.markets[:400]:
            self.totals["markets_considered"] += 1
            try:
                mapping = map_market(market, self.data["games"], now=now)
                self.totals["mapped"] += 1
                if mapping.game_id not in self.last_eligible_games:
                    self.last_eligible_games.append(mapping.game_id)
                target = self._target(self.data, mapping)
                prediction = predict_game(
                    self.data["games"],
                    target,
                    mapping.selected_team_id,
                    now,
                    method="frequency" if target.league == "NFL" else "elo",
                )
                book = books.get(market.token_id)
                health = assess_book(book, now, expected_token=market.token_id, max_spread=0.05)
                if (
                    not health.healthy
                    or book.market_id != market.market_id
                    or book.exchange != "polymarket"
                    or book.source not in PUBLIC_BOOK_SOURCES
                ):
                    raise ValueError("fresh_executable_sports_baseline_required")
                self.relationship_status = self.relationships.observe(
                    mapping,
                    prediction,
                    market_probability=(book.bids[0].price + book.asks[0].price) / 2,
                    market_timestamp=book.timestamp,
                    market_available_at=book.available_at,
                    evidence_sha256=content_sha256(book.model_dump(mode="json")),
                    now=now,
                )
                if (market.market_id, prediction.model_sha256, now.date()) in existing:
                    continue
                if target.league == "NFL":
                    self._append_ternary(market, book, mapping, prediction, now)
                else:
                    self._append(market, book, mapping, prediction, now, parents)
                existing.add((market.market_id, prediction.model_sha256, now.date()))
                created += 1
                if created >= self.max_forecasts:
                    break
            except Exception as error:  # noqa: BLE001 - mapping/model/data insufficiency is explicit
                reason = str(error)[:96] if isinstance(error, ValueError) else type(error).__name__
                self._reject(reason)
                if len(self.latest_candidates) < 8:
                    self.latest_candidates.append({"market_id": market.market_id, "reason": reason})

    def _append_ternary(self, market, book, mapping, prediction, now):
        """Store actual W/T/L probabilities without mislabeling market payout as Pwin."""
        from neraium_poly.research.phase13.mapping import map_market
        from neraium_poly.research.phase13.models import predict_game

        prediction = SportsPrediction.model_validate(prediction.model_dump())
        if now > self.clock() or (self.clock() - now).total_seconds() > 30:
            raise ValueError("prospective_sports_forecast_must_be_recorded_now")
        if (mapping.event_start - now).total_seconds() <= 300:
            raise ValueError("sports_event_start_too_close_or_past")
        # Independent replay from original raw bytes is required immediately
        # before append, not just an in-memory `qualified` assertion.
        data = self._load(self.snapshot)
        original = map_market(market, data["games"], now=now)
        if original != mapping:
            raise ValueError("sports_mapping_replay_failed")
        target = self._target(data, mapping)
        replay = predict_game(data["games"], target, mapping.selected_team_id, now, method="frequency")
        if replay != prediction or now >= mapping.event_start:
            raise ValueError("sports_model_replay_failed")
        if any(a.available_at > now for a in data["artifacts"]):
            raise ValueError("sports_source_not_available_at_forecast")
        probabilities = prediction.uncertainty.get("outcome_probabilities")
        if not probabilities:
            raise ValueError("explicit_ternary_distribution_required")
        payload = {
            "schema_version": "1.0",
            "kind": "independent_ternary_research",
            "timestamp": now.isoformat(),
            "evidence_cutoff": now.isoformat(),
            "mapping": mapping.model_dump(mode="json"),
            "prediction": prediction.model_dump(mode="json"),
            "market": market.model_dump(mode="json"),
            "book": book.model_dump(mode="json"),
            "snapshot": self.snapshot,
            "source_dataset_sha256": self._dataset_identity(data),
            "market_expected_payout_baseline": (book.bids[0].price + book.asks[0].price) / 2,
            "market_win_probability": None,
            "baseline_comparison": "Expected payout quote; no market W/T/L distribution available",
            "dependency_group": "unreviewed-sports-game:" + mapping.league + ":" + mapping.game_id,
            "independence_reviewed": False,
            "trading_authority": False,
            "certification_authority": False,
        }
        identity = content_sha256(
            [
                "ternary-sports-v1",
                mapping.game_id,
                market.market_id,
                prediction.model_sha256,
                now.date().isoformat(),
            ]
        )
        if self.journal.append("forecast", identity, {"id": identity, **payload}):
            self.totals["independent_forecasts"] += 1
        self._reject("binary_ledger_expected_payout_not_win_probability")
        self._reject("event_strategy_not_enabled_for_experimental_operation")
        self.latest_candidates.append(
            {
                "market_id": market.market_id,
                "forecast_id": identity,
                "status": "independent_ternary_research_only",
            }
        )

    def _append(self, market, book, mapping: SportsMapping, prediction: SportsPrediction, now, parents):
        evidence = []
        context = {
            "type": "qualified_sports_forecast_v1",
            "snapshot": self.snapshot,
            "source_dataset_sha256": self._dataset_identity(self.data),
            "mapping": mapping.model_dump(mode="json"),
            "prediction": prediction.model_dump(mode="json"),
            "event_start": mapping.event_start.isoformat(),
            "trading_authority": False,
        }
        for kind, source, timestamp, payload, independent in (
            ("order_book", book.source, book.timestamp, {"book": book.model_dump(mode="json")}, False),
            (
                "resolution_rules",
                market.source,
                market.timestamp,
                {"market": market.model_dump(mode="json")},
                False,
            ),
            (
                "external_context",
                self.data["artifacts"][0].source_url,
                max(a.available_at for a in self.data["artifacts"]),
                context,
                True,
            ),
        ):
            record = EventEvidence(
                id=content_sha256(["sports-evidence-v1", kind, payload, now.isoformat()]),
                timestamp=timestamp,
                available_at=now,
                source=source,
                event_id=market.event_id,
                market_id=market.market_id,
                kind=kind,
                content_sha256=content_sha256(payload),
                payload=payload,
                independent_of_market_price=independent,
            )
            self.ledger.record_evidence(record)
            evidence.append(record)
        forecast = EventForecast(
            id=content_sha256(
                [
                    "sports-independent-v1",
                    market.market_id,
                    market.token_id,
                    prediction.model_sha256,
                    now.date().isoformat(),
                ]
            ),
            timestamp=now,
            available_at=now,
            source="neraium-poly/independent-sports-research/v1",
            event_id=market.event_id,
            market_id=market.market_id,
            token_id=market.token_id,
            dependency_group=parents.get(market.event_id, "unreviewed-parent:" + market.event_id),
            category="Sports",
            kind="independent_model",
            probability=prediction.probability,
            market_probability=(book.bids[0].price + book.asks[0].price) / 2,
            evidence_cutoff=now,
            model_version=prediction.model_version,
            feature_version=prediction.feature_version,
            dataset_sha256=prediction.dataset_sha256,
            model_sha256=prediction.model_sha256,
            resolution_rules_sha256=mapping.rules_sha256,
            evidence_ids=tuple(e.id for e in evidence),
            uncertainty=prediction.uncertainty,
            lower_probability=prediction.lower_probability,
            upper_probability=prediction.upper_probability,
            horizon_seconds=(mapping.event_start - now).total_seconds(),
            calibration_status=prediction.calibration_status,
        )
        if self.ledger.record_forecast(forecast):
            self.totals["independent_forecasts"] += 1
        proposal = assess_event_proposal(forecast, market, book, now=now, enabled=False)
        self.rejections.update(proposal["reasons"])
        self.totals["proposal_evaluations"] += 1
        self.latest_candidates.append(
            {
                "market_id": market.market_id,
                "forecast_id": forecast.id,
                "status": "research_only",
                "reasons": proposal["reasons"],
            }
        )

    def corroborate_outcome(self, outcome, market, forecast):
        from neraium_poly.research.phase13.outcomes import corroborate_sports_outcome

        self.outcome_status["checks"] += 1
        try:
            evidence = [self.ledger._evidence(i) for i in forecast.evidence_ids]
            context = next(e for e in evidence if e.kind == "external_context")
            mapping = SportsMapping.model_validate(context.payload["mapping"])
            if self.data is None:
                raise ValueError("fresh_external_result_unavailable")
            result = corroborate_sports_outcome(
                outcome,
                forecast,
                market,
                mapping,
                self.data["games"],
                self.data["artifacts"],
                now=self.clock(),
            )
            if result["accepted"]:
                self.outcome_status["corroborated"] += 1
            self.outcome_status["last_result"] = result
            return result
        except Exception as error:  # noqa: BLE001 - unresolved remains unscored
            result = {"accepted": False, "status": "unresolved", "reasons": [str(error)[:120]]}
            self.outcome_status["last_result"] = result
            return result

    def replay_ternary_forecast(self, record):
        """Revalidate original independent derivation before scoring a recovered record."""
        from neraium_poly.research.phase13.mapping import map_market
        from neraium_poly.research.phase13.models import predict_game

        try:
            original = TernarySportsForecast.model_validate(record)
            data = self._load(original.snapshot)
            if self._dataset_identity(data) != original.source_dataset_sha256:
                return False
            mapping = map_market(original.market, data["games"], now=original.timestamp)
            if mapping != original.mapping or any(a.available_at > original.timestamp for a in data["artifacts"]):
                return False
            target = self._target(data, mapping)
            prediction = predict_game(data["games"], target, mapping.selected_team_id,
                                      original.timestamp, method="frequency")
            return prediction == original.prediction
        except Exception:  # noqa: BLE001 - a stored record cannot self-attest model derivation
            return False

    def _replay_outcome(self, result):
        """Reverify original source, result source and exchange proof after restart."""
        from neraium_poly.research.phase12.outcome_collector import verify_collected_outcome
        from neraium_poly.research.phase13.outcomes import corroborate_sports_outcome, score_ternary_forecast

        try:
            result = TernarySportsOutcome.model_validate(result).model_dump(mode="json")
            original = next(f for f in self.journal.records("forecast") if f["id"] == result["forecast_id"])
            if self.replay_ternary_forecast(original) is not True:
                return False
            mapping = SportsMapping.model_validate(original["mapping"])
            source = self._load(original["snapshot"])
            if self._dataset_identity(source) != original["source_dataset_sha256"]:
                return False
            data = self._load(result["current_source_snapshot"])
            market = MarketSnapshot.model_validate(original["market"])
            reference = SportsSettlementReference(
                id=original["id"],
                original_record_sha256=content_sha256(original),
                event_id=mapping.event_id,
                market_id=mapping.market_id,
                token_id=mapping.token_id,
                timestamp=datetime.fromisoformat(original["timestamp"]),
                evidence_cutoff=datetime.fromisoformat(original["evidence_cutoff"]),
                resolution_rules_sha256=mapping.rules_sha256,
            )
            outcome = VerifiedEventOutcome.model_validate(result["exchange_outcome"])
            if (
                verify_collected_outcome(outcome, market, reference, self.directory / "resolution-evidence")
                is not True
            ):
                return False
            checked = corroborate_sports_outcome(
                outcome, reference, market, mapping, data["games"], data["artifacts"], now=self.clock()
            )
            if checked != result["corroboration"]:
                return False
            game = self._target(data, mapping)
            if SportsGame.model_validate(result["sports_result"]) != game:
                return False
            if self.data is not None:
                latest = self._target(self.data, mapping)
                if (latest.status, latest.starts_at, latest.home_score, latest.away_score) != (
                    game.status,
                    game.starts_at,
                    game.home_score,
                    game.away_score,
                ):
                    return False  # Corrections suspend scoring, never rewrite original records.
            return (
                score_ternary_forecast(
                    original["prediction"]["uncertainty"]["outcome_probabilities"],
                    game,
                    mapping.selected_team_id,
                )
                == result["descriptive_scores"]
            )
        except Exception:  # noqa: BLE001 - incomplete/changed proofs withhold all scores
            return False

    async def resolve_pending(self):
        """One deferred original-forecast proof attempt, never a price-derived result."""
        from neraium_poly.research.phase12.outcome_collector import (
            acquire_verified_outcome,
            verify_collected_outcome,
        )
        from neraium_poly.research.phase13.outcomes import corroborate_sports_outcome, score_ternary_forecast

        now = self.clock()
        for result in self.journal.records("outcome"):
            identity = content_sha256(result)
            if identity not in self._approved_result_hashes and identity not in self._rejected_result_hashes:
                accepted = await asyncio.to_thread(self._replay_outcome, result)
                if accepted:
                    self._approved_result_hashes.add(identity)
                else:
                    self._rejected_result_hashes.add(identity)
                    self.outcome_status["last_error"] = (
                        "stored_sports_result_requires_reverification_or_correction_review"
                    )
                return
        resolved = {r["forecast_id"] for r in self.journal.records("outcome")}
        for record in self.journal.records("forecast"):
            mapping = SportsMapping.model_validate(record["mapping"])
            # This merely schedules proof checks. Elapsed time is never a result.
            if record["id"] in resolved or now < mapping.event_start + timedelta(hours=4):
                continue
            previous = self.result_attempts.get(record["id"])
            if previous and (now - datetime.fromisoformat(previous)).total_seconds() < 300:
                continue
            self.result_attempts[record["id"]] = now.isoformat()
            self.result_attempts = dict(sorted(self.result_attempts.items(), key=lambda x: x[1])[-400:])
            self.outcome_status["checks"] += 1
            try:
                # Revalidate original frozen external evidence even at scoring.
                original = await asyncio.to_thread(self._load, record["snapshot"])
                if self._dataset_identity(original) != record["source_dataset_sha256"]:
                    raise ValueError("original_forecast_source_integrity_failed")
                if self.data is None:
                    raise ValueError("current_external_result_unavailable")
                market = MarketSnapshot.model_validate(record["market"])
                reference = SportsSettlementReference(
                    id=record["id"],
                    original_record_sha256=content_sha256(record),
                    event_id=mapping.event_id,
                    market_id=mapping.market_id,
                    token_id=mapping.token_id,
                    timestamp=datetime.fromisoformat(record["timestamp"]),
                    evidence_cutoff=datetime.fromisoformat(record["evidence_cutoff"]),
                    resolution_rules_sha256=mapping.rules_sha256,
                )
                root = self.directory / "resolution-evidence"
                root.mkdir(exist_ok=True)
                used = sum(p.stat().st_size for p in self.directory.rglob("*") if p.is_file())
                if used + 8 * 1024**2 > self.max_bytes:
                    raise ValueError("sports_resolution_archive_budget_exhausted")
                attempt = root / (now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + record["id"][:12])
                outcome = await acquire_verified_outcome(reference, market, attempt)
                if (
                    outcome is None
                    or await asyncio.to_thread(verify_collected_outcome, outcome, market, reference, root)
                    is not True
                ):
                    raise ValueError("native_and_finalized_exchange_proof_unavailable")
                result = corroborate_sports_outcome(
                    outcome, reference, market, mapping, self.data["games"], self.data["artifacts"], now=self.clock()
                )
                if not result["accepted"]:
                    self.outcome_status["last_result"] = result
                    return
                game = self._target(self.data, mapping)
                scores = score_ternary_forecast(
                    record["prediction"]["uncertainty"]["outcome_probabilities"],
                    game,
                    mapping.selected_team_id,
                )
                self.journal.append(
                    "outcome",
                    "outcome:" + record["id"],
                    {
                        "forecast_id": record["id"],
                        "timestamp": self.clock().isoformat(),
                        "sports_result": game.model_dump(mode="json"),
                        "current_source_snapshot": self.snapshot,
                        "exchange_outcome": outcome.model_dump(mode="json"),
                        "corroboration": result,
                        "descriptive_scores": scores,
                        "independence_reviewed": False,
                        "trading_authority": False,
                    },
                )
                saved = self.journal.records("outcome")[-1]
                if await asyncio.to_thread(self._replay_outcome, saved):
                    self._approved_result_hashes.add(content_sha256(saved))
                self.outcome_status["corroborated"] += 1
                self.outcome_status["last_result"] = result
                self.outcome_status["last_error"] = None
            except Exception as error:  # noqa: BLE001 - unresolved/disputed/tie retains original record
                self.outcome_status["last_error"] = f"{type(error).__name__}:{str(error)[:120]}"
            return

    def checkpoint(self):
        return {
            "journal_head": self.journal.verify(),
            "last_attempt": self.last_attempt,
            "last_success": self.last_success,
            "snapshot": self.snapshot,
            "last_error": self.last_error,
            "rejections": dict(self.rejections),
            "totals": dict(self.totals),
            "outcome_status": self.outcome_status,
            "result_attempts": self.result_attempts,
            "relationships": self.relationships.checkpoint(),
            "relationship_status": self.relationship_status,
        }

    def summary(self):
        from neraium_poly.research.phase13.evaluation import evaluate_sports_forecasts

        forecasts, outcomes = self.journal.records("forecast"), self.journal.records("outcome")
        evaluation = evaluate_sports_forecasts(
            forecasts, outcomes, result_validator=lambda r: content_sha256(r) in self._approved_result_hashes
        )
        games = self.data["games"] if self.data else []
        now = self.clock()
        return {
            "status": "research_only" if self.data else "external_evidence_unavailable",
            "model_version": forecasts[-1]["prediction"]["model_version"] if forecasts else None,
            "model_versions": [{"model_version": v[0], "model_sha256": v[1], "feature_version": v[2]}
                               for v in sorted({(f["prediction"]["model_version"], f["prediction"]["model_sha256"],
                                                 f["prediction"]["feature_version"]) for f in forecasts})],
            "source_status": "qualified_research_only" if self.data else "unavailable",
            "upcoming_mapped_events_last_frame": len(self.last_eligible_games),
            "mapping_failures": dict(self.rejections),
            "upcoming_source_events": sum(g.status == "scheduled" and g.starts_at > now for g in games),
            "source_games": len(games),
            "source_artifacts": len(self.data["artifacts"]) if self.data else 0,
            "source_qualification": self.data.get("report", {}) if self.data else {},
            "last_source_success": self.last_success,
            "last_source_attempt": self.last_attempt,
            "last_error": self.last_error,
            "totals": dict(self.totals),
            "rejections": dict(self.rejections),
            "recent_candidates": self.latest_candidates,
            "outcome_verification": self.outcome_status,
            "trading_enabled": False,
            "certification_authority": False,
            "ternary_forecasts": len(self.journal.records("forecast")),
            "ternary_research_forecasts": len(self.journal.records("forecast")),
            "independent_binary_forecasts": 0,
            "counter_scope": "totals and rejections cumulative since Phase13 start; journal counts durable current state; recent candidates last frame",
            "ternary_pending": len(forecasts) - len(self._approved_result_hashes),
            "ternary_resolved": len(self._approved_result_hashes),
            "recorded_outcomes": len(outcomes),
            "outcomes_under_review": len(self._rejected_result_hashes),
            "outcome_reverification_pending": len(outcomes)
            - len(self._approved_result_hashes)
            - len(self._rejected_result_hashes),
            "journal_integrity": self.journal.verify(),
            "relationships": {
                "evaluations": self.relationships.evaluations,
                "descriptive_findings": self.relationships.findings,
                "latest": self.relationship_status,
                "trading_authority": False,
            },
            "scores": {
                "brier": None,
                "log_loss": None,
                "market_win_brier": None,
                "reason": "No independently reviewed resolved ternary events; market quote is expected payout, not win probability",
            },
            "evaluation": evaluation,
            "calibration_status": "insufficient prospective independent outcomes",
            "limitations": [
                "Research-only models; no automatic order admission",
                "Source snapshots first available at retrieval, never backdated",
                "No reviewed independence inferred from repeated forecasts",
            ],
        }

    def close(self):
        if self.ledger.independent_forecast_validator == self.validate_forecast:
            self.ledger.independent_forecast_validator = None
        self.journal.close()
