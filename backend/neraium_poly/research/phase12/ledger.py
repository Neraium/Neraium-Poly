"""Prospective event forecasts: immutable evidence, causal scoring, no order authority."""

import fcntl
import hashlib
import json
import math
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.research.phase12.contracts import EventEvidence, EventForecast, VerifiedEventOutcome


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_sha256(payload):
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class EventForecastLedger:
    """Separate research store; injected proof/model reviewers deny by default.

    The validator callbacks are trust boundaries supplied by an independently
    verified adapter, not fields that a forecast/outcome can assert for itself.
    A successful callback must return the literal bool True. Multiple snapshots
    are never promoted into independent events or paper account performance.
    """

    def __init__(
        self,
        directory,
        *,
        clock=None,
        outcome_validator=None,
        independent_forecast_validator=None,
        independence_validator=None,
        max_records=100000,
        max_bytes=128 * 1024**2,
    ):
        self.directory = Path(directory)
        if not 1 <= max_records <= 1000000 or not 4096 <= max_bytes <= 512 * 1024**2:
            raise ValueError("bounded forecast storage required")
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink() or any(
            (self.directory / n).exists() for n in ("risk.sqlite", "broker.sqlite")
        ):
            raise ValueError("forecast ledger must not alias an account directory")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.outcome_validator = outcome_validator
        self.independent_forecast_validator = independent_forecast_validator
        self.independence_validator = independence_validator
        self.max_records, self.max_bytes = max_records, max_bytes
        self._lock = RLock()
        self.owner = (self.directory / "forecast.lock").open("a+")
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise ValueError("another event forecast coordinator owns this ledger") from None
        try:
            self.db = sqlite3.connect(
                self.directory / "forecasts.sqlite", isolation_level=None, check_same_thread=False
            )
            self.db.row_factory = sqlite3.Row
            self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS journal(
              seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,id TEXT NOT NULL UNIQUE,
              payload TEXT NOT NULL,digest TEXT NOT NULL,previous TEXT,chain TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
              BEGIN SELECT RAISE(ABORT,'forecast journal append only'); END;
            CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
              BEGIN SELECT RAISE(ABORT,'forecast journal append only'); END;
            """)
            self.verify()
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            self.owner.close()
            raise

    @staticmethod
    def _chain(previous, kind, identity, digest):
        return content_sha256([previous, kind, identity, digest])

    def verify(self):
        with self._lock:
            previous = None
            count = 0
            for row in self.db.execute("SELECT * FROM journal ORDER BY seq"):
                count += 1
                if count > self.max_records:
                    raise ValueError("forecast record budget exceeded")
                if (
                    hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]
                    or row["previous"] != previous
                    or row["chain"] != self._chain(previous, row["kind"], row["id"], row["digest"])
                ):
                    raise ValueError("corrupt forecast evidence chain")
                previous = row["chain"]
            return {"records": count, "head_sha256": previous, "integrity": "verified"}

    def _append(self, kind, record):
        payload = canonical(record.model_dump(mode="json"))
        if len(payload.encode()) > 256 * 1024:
            raise ValueError("forecast record byte limit exceeded")
        with self._lock:
            existing = self.db.execute("SELECT kind,payload FROM journal WHERE id=?", (record.id,)).fetchone()
            if existing:
                if existing["kind"] != kind or existing["payload"] != payload:
                    raise ValueError("immutable forecast record ID collision")
                return False
            size = sum(p.stat().st_size for p in self.directory.glob("forecasts.sqlite*"))
            if (
                size + len(payload.encode()) > self.max_bytes
                or self.db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] >= self.max_records
            ):
                raise ValueError("forecast storage budget exhausted")
            if shutil.disk_usage(self.directory).free < 8 * 1024**3:
                raise ValueError("forecast free-disk floor reached")
            previous = self.db.execute("SELECT chain FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
            previous = previous[0] if previous else None
            digest = hashlib.sha256(payload.encode()).hexdigest()
            self.db.execute(
                "INSERT INTO journal(kind,id,payload,digest,previous,chain) VALUES(?,?,?,?,?,?)",
                (kind, record.id, payload, digest, previous, self._chain(previous, kind, record.id, digest)),
            )
            return True

    def record_evidence(self, record):
        record = EventEvidence.model_validate(record)
        now = self.clock()
        if record.available_at > now or content_sha256(record.payload) != record.content_sha256:
            raise ValueError("future or corrupt event evidence")
        return self._append("evidence", record)

    def _evidence(self, identity):
        row = self.db.execute(
            "SELECT payload FROM journal WHERE kind='evidence' AND id=?", (identity,)
        ).fetchone()
        if row is None:
            raise ValueError("forecast references missing evidence")
        return EventEvidence.model_validate_json(row[0])

    def record_forecast(self, forecast):
        forecast = EventForecast.model_validate(forecast)
        with self._lock:
            old = self.db.execute("SELECT kind,payload FROM journal WHERE id=?", (forecast.id,)).fetchone()
            if old:
                return self._append("forecast", forecast)
            now = self.clock()
            if (
                now.tzinfo is None
                or forecast.available_at > now
                or (now - forecast.timestamp).total_seconds() > 30
            ):
                raise ValueError("prospective forecast must be recorded now, never backdated")
            if len(set(forecast.evidence_ids)) != len(forecast.evidence_ids):
                raise ValueError("duplicate forecast evidence")
            evidence = [self._evidence(i) for i in forecast.evidence_ids]
            if any(
                e.event_id != forecast.event_id
                or e.market_id != forecast.market_id
                or e.available_at > forecast.evidence_cutoff
                or e.timestamp > forecast.evidence_cutoff
                for e in evidence
            ):
                raise ValueError("noncausal or mismatched forecast evidence")
            rules = [e for e in evidence if e.kind == "resolution_rules"]
            rule_payloads = [e.payload.get("market", e.payload) for e in rules]
            if not any(
                payload.get("resolution_rules")
                and payload.get("resolution_source")
                and hashlib.sha256(payload["resolution_rules"].encode()).hexdigest()
                == forecast.resolution_rules_sha256
                for payload in rule_payloads
            ):
                raise ValueError("matching resolution rules and source required")
            for payload in rule_payloads:
                if "market_id" in payload:
                    market = MarketSnapshot.model_validate(payload)
                    if (
                        (market.event_id, market.market_id, market.token_id)
                        != (forecast.event_id, forecast.market_id, forecast.token_id)
                        or market.available_at > forecast.evidence_cutoff
                        or market.status != "active"
                        or (market.end_time is not None and market.end_time <= forecast.timestamp)
                    ):
                        raise ValueError("unsupported or noncausal settlement metadata")
            books = []
            for e in evidence:
                if e.kind == "order_book":
                    b = OrderBookSnapshot.model_validate(e.payload.get("book", e.payload))
                    if (
                        b.source
                        in {
                            "https://clob.polymarket.com",
                            "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                        }
                        and b.exchange == "polymarket"
                        and b.market_id == forecast.market_id
                        and b.token_id == forecast.token_id
                        and assess_book(b, forecast.timestamp, max_spread=0.05).healthy
                    ):
                        books.append(b)
            if not any(
                abs((b.bids[0].price + b.asks[0].price) / 2 - forecast.market_probability) <= 1e-12
                for b in books
            ):
                raise ValueError("contemporaneous executable market baseline required")
            if (
                forecast.kind == "market_baseline"
                and abs(forecast.probability - forecast.market_probability) > 1e-12
            ):
                raise ValueError("market baseline cannot claim independent probability")
            if forecast.kind == "historical_frequency" and (
                self.independent_forecast_validator is None
                or self.independent_forecast_validator(forecast, tuple(evidence)) is not True
            ):
                raise ValueError("reviewed historical-frequency training provenance required")
            if forecast.kind == "independent_model":
                external = [
                    e
                    for e in evidence
                    if e.kind == "external_context"
                    and e.independent_of_market_price
                    and "polymarket.com" not in e.source.lower()
                ]
                if (
                    not external
                    or self.independent_forecast_validator is None
                    or self.independent_forecast_validator(forecast, tuple(evidence)) is not True
                ):
                    raise ValueError("independently reviewed model and external context required")
            if forecast.independence_reviewed and (
                self.independence_validator is None or self.independence_validator(forecast) is not True
            ):
                raise ValueError("independent event grouping review required")
            for previous in self.forecasts():
                if (
                    previous.event_id == forecast.event_id
                    and previous.dependency_group != forecast.dependency_group
                ):
                    raise ValueError("inconsistent dependency group for the same event")
            for row in self.db.execute("SELECT payload FROM journal WHERE kind='outcome'"):
                outcome = VerifiedEventOutcome.model_validate_json(row[0])
                if outcome.market_id == forecast.market_id and outcome.token_id == forecast.token_id:
                    raise ValueError("cannot forecast a known resolved outcome")
            return self._append("forecast", forecast)

    def record_outcome(self, outcome):
        outcome = VerifiedEventOutcome.model_validate(outcome)
        with self._lock:
            old = self.db.execute("SELECT kind,payload FROM journal WHERE id=?", (outcome.id,)).fetchone()
            if old:
                return self._append("outcome", outcome)
            if (
                outcome.available_at > self.clock()
                or content_sha256(outcome.verification) != outcome.proof_sha256
            ):
                raise ValueError("future or unbound outcome proof")
            if self.outcome_validator is None or self.outcome_validator(outcome) is not True:
                raise ValueError("independent finalized outcome proof verification required")
            for row in self.db.execute("SELECT payload FROM journal WHERE kind='outcome'"):
                prior = VerifiedEventOutcome.model_validate_json(row[0])
                if (prior.market_id, prior.token_id) == (
                    outcome.market_id,
                    outcome.token_id,
                ) and prior != outcome:
                    raise ValueError("conflicting finalized outcome; correction requires separate review")
            return self._append("outcome", outcome)

    def forecasts(self):
        with self._lock:
            return tuple(
                EventForecast.model_validate_json(r[0])
                for r in self.db.execute("SELECT payload FROM journal WHERE kind='forecast' ORDER BY seq")
            )

    def pending_forecasts(self):
        with self._lock:
            resolved = {
                (o.market_id, o.token_id)
                for o in (
                    VerifiedEventOutcome.model_validate_json(r[0])
                    for r in self.db.execute("SELECT payload FROM journal WHERE kind='outcome'")
                )
            }
            return tuple(f for f in self.forecasts() if (f.market_id, f.token_id) not in resolved)

    @staticmethod
    def _metrics(rows):
        if not rows:
            return {
                "count": 0,
                "brier": None,
                "log_loss": None,
                "market_brier": None,
                "market_log_loss": None,
                "ece": None,
                "reliability": [],
                "confidence_interval": None,
                "reason": "No independently reviewed resolved event groups",
            }
        n = len(rows)

        def loss(prob, y):
            p = min(1 - 1e-12, max(1e-12, prob))
            return -(y * math.log(p) + (1 - y) * math.log(1 - p))

        bins = []
        for i in range(10):
            group = [(f, o) for f, o in rows if min(9, int(f.probability * 10)) == i]
            if group:
                bins.append(
                    {
                        "bin": i,
                        "count": len(group),
                        "mean_probability": sum(f.probability for f, _ in group) / len(group),
                        "observed_rate": sum(o.payout for _, o in group) / len(group),
                    }
                )
        return {
            "count": n,
            "brier": sum((f.probability - o.payout) ** 2 for f, o in rows) / n,
            "log_loss": sum(loss(f.probability, o.payout) for f, o in rows) / n,
            "market_brier": sum((f.market_probability - o.payout) ** 2 for f, o in rows) / n,
            "market_log_loss": sum(loss(f.market_probability, o.payout) for f, o in rows) / n,
            "ece": sum(b["count"] * abs(b["mean_probability"] - b["observed_rate"]) for b in bins) / n,
            "reliability": bins,
            "confidence_interval": None,
            "reason": "Descriptive resolved-group scores; confidence intervals require a larger independent sample",
        }

    def summary(self, now=None):
        with self._lock:
            integrity = self.verify()
            now = now or self.clock()
            forecasts, outcomes = [], {}
            for row in self.db.execute(
                "SELECT kind,payload FROM journal WHERE kind IN ('forecast','outcome') ORDER BY seq"
            ):
                if row["kind"] == "forecast":
                    forecast = EventForecast.model_validate_json(row["payload"])
                    if forecast.available_at <= now:
                        forecasts.append(forecast)
                else:
                    o = VerifiedEventOutcome.model_validate_json(row["payload"])
                    if o.available_at <= now:
                        outcomes[(o.event_id, o.market_id, o.token_id)] = o
            resolved, pending, rejected = [], [], 0
            for f in forecasts:
                o = outcomes.get((f.event_id, f.market_id, f.token_id))
                if o is None:
                    pending.append(f)
                elif (
                    f.timestamp < o.settled_at
                    and f.evidence_cutoff < o.settled_at
                    and f.resolution_rules_sha256 == o.resolution_rules_sha256
                ):
                    resolved.append((f, o))
                else:
                    rejected += 1
            # Earliest immutable forecast per dependency group/model/kind. Repeated
            # tokens, parent events and snapshots cannot inflate score samples.
            grouped = {}
            for f, o in resolved:
                key = (f.dependency_group, f.kind, f.model_version, f.model_sha256, f.feature_version)
                grouped.setdefault(key, (f, o))
            eligible = [(f, o) for f, o in grouped.values() if f.independence_reviewed]
            primary = {}
            baseline = {}
            for f, o in eligible:
                if f.kind == "independent_model":
                    primary.setdefault(f.dependency_group, (f, o))
                if f.kind == "market_baseline":
                    baseline.setdefault(f.dependency_group, (f, o))
            by_model = {}
            for f, o in eligible:
                model_key = canonical([f.model_version, f.model_sha256, f.feature_version])
                by_model.setdefault(model_key, []).append((f, o))
            return {
                "schema_version": "1.0",
                "status": "prospective_research",
                "generated_at": now.isoformat(),
                "events_tracked": len({f.event_id for f in forecasts}),
                "forecasts": len(forecasts),
                "forecasts_pending": len(pending),
                "forecasts_resolved": len(resolved),
                "resolved_forecast_groups": len(grouped),
                "independent_event_groups": len({f.dependency_group for f, _ in eligible}),
                "market_baseline_forecasts": sum(f.kind == "market_baseline" for f in forecasts),
                "independent_model_forecasts": sum(f.kind == "independent_model" for f in forecasts),
                "model_versions": sorted({f.model_version for f in forecasts}),
                "model_identities": [
                    json.loads(key)
                    for key in sorted(
                        {canonical([f.model_version, f.model_sha256, f.feature_version]) for f in forecasts}
                    )
                ],
                "scores": self._metrics(list(primary.values())),
                "baseline_scores": self._metrics(list(baseline.values())),
                "model_scores": {k: self._metrics(v) for k, v in by_model.items()},
                "uncalibrated_resolved_scores": self._metrics(list(grouped.values())),
                "calibration_status": "insufficient independent evidence"
                if not eligible
                else "descriptive independent-group outcomes; unvalidated",
                "market_baseline": "Contemporaneous observed bid/ask midpoint; not independent forecasting skill",
                "rejected_outcome_matches": rejected,
                "integrity": integrity,
                "certification_authority": False,
                "automatic_promotion": False,
                "limitations": [
                    "Repeated forecasts do not create independent event observations",
                    "Market-baseline records are not independent model forecasts",
                    "No account, order or strategy-approval authority",
                ],
            }

    def close(self):
        self.db.close()
        fcntl.flock(self.owner, fcntl.LOCK_UN)
        self.owner.close()
