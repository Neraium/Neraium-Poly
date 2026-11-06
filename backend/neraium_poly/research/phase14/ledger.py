"""Domain-neutral typed admission over the existing append-only forecast engine.

Separate child ownership protects old schemas. No record creates strategy, risk,
account or order authority. All provider/model/outcome reviews deny by default.
"""

import hashlib
from datetime import UTC, datetime

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import EventForecastLedger, content_sha256
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence, DomainForecast


class UniversalForecastLedger:
    def __init__(
        self,
        directory,
        *,
        clock=None,
        forecast_validator=None,
        outcome_validator=None,
        anchor=None,
        max_bytes=64 * 1024**2,
    ):
        self.clock = clock or (lambda: datetime.now(UTC))
        self.forecast_validator, self.outcome_validator = forecast_validator, outcome_validator
        self.engine = EventForecastLedger(
            directory, clock=self.clock, max_records=20000, max_bytes=max_bytes, max_record_bytes=512 * 1024
        )
        try:
            actual = self.engine.verify()
            if anchor:
                row = self.engine.db.execute(
                    "SELECT chain FROM journal WHERE seq=?", (anchor["records"],)
                ).fetchone()
                if actual["records"] < anchor["records"] or (
                    anchor["records"] and (not row or row[0] != anchor["head_sha256"])
                ):
                    raise ValueError("domain journal rollback detected")
            self.verify()
        except BaseException:
            self.engine.close()
            raise

    def _records(self, kind, schema):
        result = []
        for row in self.engine.db.execute("SELECT payload FROM journal WHERE kind=? ORDER BY seq", (kind,)):
            result.append(schema.model_validate_json(row[0]))
        return result

    def evidence(self):
        return self._records("domain_evidence", DomainEvidence)

    def forecasts(self):
        return self._records("domain_forecast", DomainForecast)

    def outcomes(self):
        return self._records("domain_outcome", VerifiedEventOutcome)

    def _matching_forecasts(self, outcome):
        return tuple(
            f for f in self.forecasts()
            if (f.event_id, f.market_id, f.token_id) == (outcome.event_id, outcome.market_id, outcome.token_id)
            and f.timestamp < outcome.settled_at
            and f.rules_sha256 == outcome.resolution_rules_sha256
        )

    def verified_outcomes(self):
        # Journal integrity is distinct from current source-proof verification.
        # A restart drops verifier authority until original proofs replay successfully.
        return [o for o in self.outcomes() if self.outcome_validator is not None
                and self.outcome_validator(o, self._matching_forecasts(o)) is True]

    def verify(self):
        integrity = self.engine.verify()
        for e in self.evidence():
            if content_sha256(e.payload) != e.content_sha256:
                raise ValueError("corrupt domain evidence")
        schemas = {
            "domain_evidence": DomainEvidence,
            "domain_forecast": DomainForecast,
            "domain_outcome": VerifiedEventOutcome,
        }
        for row in self.engine.db.execute("SELECT kind,id,payload FROM journal ORDER BY seq"):
            if row["kind"] not in schemas:
                raise ValueError("unknown universal journal record type")
            record = schemas[row["kind"]].model_validate_json(row["payload"])
            if record.id != row["id"]:
                raise ValueError("universal journal payload identity mismatch")
        available = {e.id: e for e in self.evidence()}
        for f in self.forecasts():
            try:
                c = DomainContract.model_validate(f.contemporaneous_market["contract"])
                m = MarketSnapshot.model_validate(f.contemporaneous_market["market"])
                selected = tuple(available[i] for i in f.evidence_ids)
                if self.forecast_validator is None or self.forecast_validator(f, c, m, selected) is not True:
                    raise ValueError("stored forecast model replay failed")
            except (KeyError, ValueError) as error:
                raise ValueError("unverified stored domain forecast derivation") from error
        for o in self.outcomes():
            if content_sha256(o.verification) != o.proof_sha256 or not self._matching_forecasts(o):
                raise ValueError("corrupt or unmatched stored domain outcome")
        return integrity

    def record_evidence(self, value):
        e = DomainEvidence.model_validate(value.model_dump() if isinstance(value, DomainEvidence) else value)
        if e.available_at > self.clock() or content_sha256(e.payload) != e.content_sha256:
            raise ValueError("future or corrupt domain evidence")
        return self.engine._append("domain_evidence", e)

    def record_forecast(self, value, *, contract, market, book):
        with self.engine._lock:
            return self._record_forecast(value, contract=contract, market=market, book=book)

    def _record_forecast(self, value, *, contract, market, book):
        f = DomainForecast.model_validate(value.model_dump() if isinstance(value, DomainForecast) else value)
        c = DomainContract.model_validate(
            contract.model_dump() if isinstance(contract, DomainContract) else contract
        )
        m = MarketSnapshot.model_validate(
            market.model_dump() if isinstance(market, MarketSnapshot) else market
        )
        b = OrderBookSnapshot.model_validate(
            book.model_dump() if isinstance(book, OrderBookSnapshot) else book
        )
        now = self.clock()
        if f.available_at > now or f.timestamp > now or (now - f.timestamp).total_seconds() > 30:
            raise ValueError("domain forecast must be recorded prospectively now")
        if not c.compatible or c.review_required or m.status != "active":
            raise ValueError("reviewed compatible domain resolution rules required")
        identities = [(r.event_id, r.market_id, r.token_id) for r in (f, c, m)]
        if len(set(identities)) != 1 or c.domain != f.domain or c.contract_type != f.contract_type:
            raise ValueError("domain contract identity mismatch")
        if (
            f.rules_sha256 != c.rules_sha256
            or f.rules_sha256 != hashlib.sha256(m.resolution_rules.encode()).hexdigest()
            or not m.resolution_source
            or m.available_at > f.evidence_cutoff
            or c.timestamp > f.evidence_cutoff
            or c.available_at > f.evidence_cutoff
            or (m.end_time and m.end_time <= f.timestamp)
            or c.probability_semantics != f.probability_semantics
        ):
            raise ValueError("noncausal or unsupported domain settlement semantics")
        if (
            not assess_book(b, f.timestamp, expected_token=f.token_id, max_spread=0.05).healthy
            or b.market_id != f.market_id
            or b.source not in PUBLIC_BOOK_SOURCES
            or b.exchange != "polymarket"
            or f.contemporaneous_market.get("book") != b.model_dump(mode="json")
            or f.contemporaneous_market.get("market") != m.model_dump(mode="json")
            or f.contemporaneous_market.get("contract") != c.model_dump(mode="json")
        ):
            raise ValueError("authentic current executable domain comparison required")
        if len(set(f.evidence_ids)) != len(f.evidence_ids):
            raise ValueError("duplicate domain evidence")
        available = {e.id: e for e in self.evidence()}
        selected = tuple(available.get(i) for i in f.evidence_ids)
        if not f.independent_of_polymarket or any(
            e is None
            or e.domain != f.domain
            or not e.independent_of_polymarket
            or e.qualification != "qualified_research"
            or e.available_at > f.evidence_cutoff
            or e.timestamp > f.evidence_cutoff
            or "polymarket.com" in e.source.lower()
            for e in selected
        ):
            raise ValueError("qualified causal independent domain evidence required")
        if self.forecast_validator is None or self.forecast_validator(f, c, m, selected) is not True:
            raise ValueError("independent domain model replay required")
        if any(o.event_id == f.event_id and o.market_id == f.market_id for o in self.outcomes()):
            raise ValueError("cannot forecast known resolved domain event")
        if any(
            old.event_id == f.event_id and old.dependency_group != f.dependency_group
            for old in self.forecasts()
        ):
            raise ValueError("inconsistent dependency group for same domain event")
        return self.engine._append("domain_forecast", f)

    def record_outcome(self, value):
        with self.engine._lock:
            return self._record_outcome(value)

    def _record_outcome(self, value):
        o = VerifiedEventOutcome.model_validate(
            value.model_dump() if isinstance(value, VerifiedEventOutcome) else value
        )
        matching = [
            f
            for f in self.forecasts()
            if (f.event_id, f.market_id, f.token_id) == (o.event_id, o.market_id, o.token_id)
            and f.timestamp < o.settled_at
            and f.rules_sha256 == o.resolution_rules_sha256
        ]
        if (
            not matching
            or o.available_at > self.clock()
            or content_sha256(o.verification) != o.proof_sha256
            or self.outcome_validator is None
            or self.outcome_validator(o, tuple(matching)) is not True
        ):
            raise ValueError("independently verified matching domain outcome required")
        for previous in self.outcomes():
            if (previous.event_id, previous.market_id, previous.token_id) == (
                o.event_id,
                o.market_id,
                o.token_id,
            ) and previous != o:
                raise ValueError("domain outcome correction requires separate review; originals immutable")
        return self.engine._append("domain_outcome", o)

    def summary(self):
        forecasts, outcomes = self.forecasts(), self.verified_outcomes()
        verified = {(o.event_id, o.market_id, o.token_id) for o in outcomes}
        domains = {}
        for f in forecasts:
            row = domains.setdefault(
                f.domain, {"forecasts": 0, "pending": 0, "resolved": 0, "model_versions": set()}
            )
            row["forecasts"] += 1
            row["resolved" if (f.event_id, f.market_id, f.token_id) in verified else "pending"] += 1
            row["model_versions"].add(f.model_version)
        for row in domains.values():
            row["model_versions"] = sorted(row["model_versions"])
        return {
            "integrity": self.verify(),
            "domains": domains,
            "forecasts": len(forecasts),
            "outcomes": len(outcomes),
            "stored_outcomes_requiring_review": len(self.outcomes()) - len(outcomes),
            "evidence_records": len(self.evidence()),
            "independent_reviewed_event_groups": 0,
            "brier": None,
            "log_loss": None,
            "calibration": None,
            "market_skill_comparison": None,
            "reason": "No reviewed independent resolved domain cohort",
            "trading_authority": False,
            "certification_authority": False,
        }

    def close(self):
        self.engine.close()
