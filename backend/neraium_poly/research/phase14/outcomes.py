"""Universal scheduled proof interface; unsupported domain corroboration denies.

Native exchange finality alone is insufficient. A separately registered domain
result verifier must replay the exact source, settlement definition and evidence.
No domain verifier is automatically approved by this phase.
"""

import asyncio
from datetime import datetime

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase12.contracts import SettlementProofReference
from neraium_poly.research.phase12.ledger import content_sha256


class DomainOutcomeCollector:
    def __init__(self, ledger, *, clock, verifiers=None, state=None):
        self.ledger, self.clock = ledger, clock
        self.verifiers = dict(verifiers or {})
        self.state = {"checks": 0, "verified": 0, **(state or {})}
        self.accepted = {}
        if ledger.outcome_validator is not None:
            raise ValueError("cannot replace domain outcome authority")
        ledger.outcome_validator = self._accepted

    def _accepted(self, outcome, matching):
        return bool(matching) and self.accepted.get(outcome.id) == outcome.model_dump(mode="json")

    async def _reverify_stored(self, verify_collected_outcome):
        # Never trust a persisted verification flag after restart or source correction.
        self.accepted.clear()
        root = self.ledger.engine.directory / "resolution-evidence"
        for outcome in self.ledger.outcomes():
            matching = self.ledger._matching_forecasts(outcome)
            for f in matching:
                verifier = self.verifiers.get(f.domain)
                if verifier is None:
                    self.state["last_error"] = "stored_domain_outcome_requires_source_reverification"
                    continue
                market = MarketSnapshot.model_validate(f.contemporaneous_market["market"])
                reference = self._reference(f)
                try:
                    native = await asyncio.to_thread(
                        verify_collected_outcome, outcome, market, reference, root
                    )
                    corroborated = verifier(outcome, f, market) if native else False
                    if asyncio.iscoroutine(corroborated):
                        corroborated = await corroborated
                    if native and corroborated is True:
                        self.accepted[outcome.id] = outcome.model_dump(mode="json")
                        break
                except Exception as error:  # noqa: BLE001 - immutable record remains under review
                    self.state["last_error"] = f"stored_outcome_reverification:{type(error).__name__}"

    @staticmethod
    def _reference(f):
        return SettlementProofReference(
            id=f.id, event_id=f.event_id, market_id=f.market_id, token_id=f.token_id,
            timestamp=f.timestamp, evidence_cutoff=f.evidence_cutoff,
            resolution_rules_sha256=f.rules_sha256,
            original_record_sha256=content_sha256(f.model_dump(mode="json")),
        )

    async def check_pending(self):
        from neraium_poly.research.phase12.outcome_collector import (
            acquire_verified_outcome,
            verify_collected_outcome,
        )

        await self._reverify_stored(verify_collected_outcome)
        resolved = {(o.event_id, o.market_id, o.token_id) for o in self.ledger.verified_outcomes()}
        now = self.clock()
        for f in self.ledger.forecasts():
            if (f.event_id, f.market_id, f.token_id) in resolved:
                continue
            market = MarketSnapshot.model_validate(f.contemporaneous_market["market"])
            if market.end_time is None or market.end_time > now:
                continue
            verifier = self.verifiers.get(f.domain)
            if verifier is None:
                self.state["last_error"] = "independent_domain_outcome_source_not_qualified"
                continue
            previous = self.state.get("last_checked_at")
            if previous and (now - datetime.fromisoformat(previous)).total_seconds() < 300:
                return
            self.state.update(last_checked_at=now.isoformat(), checks=self.state["checks"] + 1)
            reference = self._reference(f)
            root = self.ledger.engine.directory / "resolution-evidence"
            output = root / (now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + content_sha256(f.id)[:12])
            try:
                outcome = await acquire_verified_outcome(reference, market, output)
                if outcome is None or not await asyncio.to_thread(
                    verify_collected_outcome, outcome, market, reference, root
                ):
                    raise ValueError("native_finalized_domain_proof_unavailable")
                verified = verifier(outcome, f, market)
                if asyncio.iscoroutine(verified):
                    verified = await verified
                if verified is not True:
                    raise ValueError("independent_domain_result_corroboration_required")
                self.accepted[outcome.id] = outcome.model_dump(mode="json")
                self.ledger.record_outcome(outcome)
                self.state.update(verified=self.state["verified"] + 1, last_error=None)
            except Exception as error:  # noqa: BLE001 - preserve pending state and all original records
                self.state["last_error"] = f"{type(error).__name__}:{str(error)[:120]}"
            return

    def close(self):
        if self.ledger.outcome_validator == self._accepted:
            self.ledger.outcome_validator = None
