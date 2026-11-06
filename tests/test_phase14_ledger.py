"""Controlled cross-domain ledger fixtures; never genuine forecasts or market evidence."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence, DomainForecast
from neraium_poly.research.phase14.ledger import UniversalForecastLedger
from test_experimental_account import book, market

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def records(domain="weather", token="test-token"):
    m, b = market(NOW, token), book(NOW, token)
    rules = hashlib.sha256(m.resolution_rules.encode()).hexdigest()
    c = DomainContract(
        id="c-" + token,
        timestamp=NOW,
        available_at=NOW,
        source="CONTROLLED",
        domain=domain,
        event_id=m.event_id,
        market_id=m.market_id,
        token_id=m.token_id,
        contract_type="CONTROLLED",
        probability_semantics="binary_event_probability",
        rules_sha256=rules,
        parameters={"fixture": True},
        compatible=True,
        review_required=False,
    )
    payload = {"CONTROLLED_fixture": True}
    e = DomainEvidence(
        id="e-" + domain,
        timestamp=NOW,
        available_at=NOW,
        source="https://fixture.invalid",
        domain=domain,
        provider="CONTROLLED",
        source_id="e",
        retrieved_at=NOW,
        content_sha256=content_sha256(payload),
        payload=payload,
        independent_of_polymarket=True,
        qualification="qualified_research",
    )
    f = DomainForecast(
        id="f-" + token,
        timestamp=NOW,
        available_at=NOW,
        source="CONTROLLED",
        domain=domain,
        event_id=m.event_id,
        market_id=m.market_id,
        token_id=m.token_id,
        contract_type=c.contract_type,
        probability_semantics=c.probability_semantics,
        probability=0.6,
        evidence_cutoff=NOW,
        model_version="CONTROLLED",
        model_sha256="a" * 64,
        feature_version="CONTROLLED",
        dataset_sha256="b" * 64,
        rules_sha256=rules,
        evidence_ids=(e.id,),
        uncertainty={"lower_probability": 0.3, "upper_probability": 0.8},
        independent_of_polymarket=True,
        dependency_group="unreviewed:" + m.event_id,
        contemporaneous_market={
            "book": b.model_dump(mode="json"),
            "market": m.model_dump(mode="json"),
            "contract": c.model_dump(mode="json"),
        },
    )
    return m, b, c, e, f


def test_two_domains_prospective_append_recovery_and_default_deny(tmp_path):
    ledger = UniversalForecastLedger(
        tmp_path / "domains", clock=lambda: NOW, forecast_validator=lambda *a: True
    )
    try:
        for domain, token in [("weather", "w"), ("crypto", "c")]:
            m, b, c, e, f = records(domain, token)
            ledger.record_evidence(e)
            assert ledger.record_forecast(f, contract=c, market=m, book=b)
        assert ledger.summary()["forecasts"] == 2
        assert set(ledger.summary()["domains"]) == {"weather", "crypto"}
        anchor = ledger.verify()
    finally:
        ledger.close()
    recovered = UniversalForecastLedger(
        tmp_path / "domains", clock=lambda: NOW, anchor=anchor, forecast_validator=lambda *a: True
    )
    try:
        assert recovered.summary()["forecasts"] == 2
    finally:
        recovered.close()
    with pytest.raises(ValueError, match="unverified stored"):
        UniversalForecastLedger(tmp_path / "domains", clock=lambda: NOW, anchor=anchor)


@pytest.mark.parametrize(
    "kind",
    [
        "future_contract",
        "missing_market",
        "unreviewed",
        "wrong_token",
        "stale_book",
        "missing_depth",
        "future_evidence",
    ],
)
def test_domain_admission_fail_closed(tmp_path, kind):
    m, b, c, e, f = records()
    now = NOW + timedelta(seconds=2)
    ledger = UniversalForecastLedger(
        tmp_path / "domains", clock=lambda: now, forecast_validator=lambda *a: True
    )
    try:
        if kind == "future_contract":
            c = c.model_copy(update={"timestamp": now, "available_at": now})
            f = f.model_copy(
                update={
                    "contemporaneous_market": {
                        **f.contemporaneous_market,
                        "contract": c.model_dump(mode="json"),
                    }
                }
            )
        elif kind == "missing_market":
            f = f.model_copy(
                update={
                    "contemporaneous_market": {
                        "book": b.model_dump(mode="json"),
                        "contract": c.model_dump(mode="json"),
                    }
                }
            )
        elif kind == "unreviewed":
            c = c.model_copy(update={"review_required": True})
        elif kind == "wrong_token":
            b = b.model_copy(update={"token_id": "wrong"})
        elif kind == "stale_book":
            b = b.model_copy(update={"timestamp": NOW - timedelta(seconds=16)})
        elif kind == "missing_depth":
            b = b.model_copy(update={"bids": ()})
        elif kind == "future_evidence":
            e = e.model_copy(update={"timestamp": now, "retrieved_at": now, "available_at": now})
        ledger.record_evidence(e)
        with pytest.raises(ValueError):
            ledger.record_forecast(f, contract=c, market=m, book=b)
        assert not ledger.forecasts()
    finally:
        ledger.close()


def test_unknown_model_duplicate_id_and_renamed_group_do_not_gain_authority(tmp_path):
    m, b, c, e, f = records()
    ledger = UniversalForecastLedger(tmp_path / "d", clock=lambda: NOW)
    try:
        ledger.record_evidence(e)
        with pytest.raises(ValueError, match="model replay"):
            ledger.record_forecast(f, contract=c, market=m, book=b)
        ledger.forecast_validator = lambda *a: True
        assert ledger.record_forecast(f, contract=c, market=m, book=b)
        assert not ledger.record_forecast(f, contract=c, market=m, book=b)
        fork = f.model_copy(update={"id": "fork", "dependency_group": "invented-group"})
        with pytest.raises(ValueError, match="dependency group"):
            ledger.record_forecast(fork, contract=c, market=m, book=b)
    finally:
        ledger.close()


def test_parallel_duplicate_processing_is_idempotent(tmp_path):
    m, b, c, e, f = records()
    ledger = UniversalForecastLedger(tmp_path / "d", clock=lambda: NOW, forecast_validator=lambda *a: True)
    try:
        ledger.record_evidence(e)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(ledger.record_forecast, f, contract=c, market=m, book=b) for _ in range(2)]
            assert sorted(j.result() for j in jobs) == [False, True]
        assert len(ledger.forecasts()) == 1
    finally:
        ledger.close()


def test_hash_consistent_recovery_rejects_untrusted_original_book(tmp_path):
    _m, b, _c, e, f = records()
    ledger = UniversalForecastLedger(tmp_path / "d", clock=lambda: NOW, forecast_validator=lambda *a: True)
    try:
        ledger.record_evidence(e)
        poisoned = f.model_copy(update={"contemporaneous_market": {
            **f.contemporaneous_market,
            "book": b.model_copy(update={"token_id": "different"}).model_dump(mode="json"),
        }})
        ledger.engine._append("domain_forecast", poisoned)
        with pytest.raises(ValueError, match="unverified stored"):
            ledger.verify()
    finally:
        ledger.close()


def test_domain_outcome_reviewer_required_and_immutable(tmp_path):
    now = [NOW]
    m, b, c, e, f = records()
    ledger = UniversalForecastLedger(tmp_path / "d", clock=lambda: now[0], forecast_validator=lambda *a: True)
    try:
        ledger.record_evidence(e)
        ledger.record_forecast(f, contract=c, market=m, book=b)
        now[0] += timedelta(days=2)
        proof = {"CONTROLLED": True}
        o = VerifiedEventOutcome(
            id="o",
            timestamp=now[0],
            available_at=now[0],
            source="CONTROLLED",
            event_id=f.event_id,
            market_id=f.market_id,
            token_id=f.token_id,
            payout=1,
            resolution_rules_sha256=f.rules_sha256,
            settled_at=now[0],
            verification_source="CONTROLLED",
            proof_sha256=content_sha256(proof),
            verification=proof,
        )
        with pytest.raises(ValueError, match="verified matching"):
            ledger.record_outcome(o)
        ledger.outcome_validator = lambda *a: True
        assert ledger.record_outcome(o)
        assert not ledger.record_outcome(o)
        with pytest.raises(ValueError, match="correction"):
            ledger.record_outcome(o.model_copy(update={"id": "corrected", "payout": 0}))
    finally:
        ledger.close()
    recovered = UniversalForecastLedger(
        tmp_path / "d", clock=lambda: now[0], forecast_validator=lambda *a: True
    )
    try:
        assert recovered.summary()["outcomes"] == 0
        assert recovered.summary()["stored_outcomes_requiring_review"] == 1
        assert recovered.summary()["domains"]["weather"]["pending"] == 1
        import asyncio

        from neraium_poly.research.phase14.outcomes import DomainOutcomeCollector

        collector = DomainOutcomeCollector(recovered, clock=lambda: now[0])
        asyncio.run(collector.check_pending())
        assert not recovered.verified_outcomes()
        assert len(recovered.outcomes()) == 1  # Original remains immutable, not silently discarded.
        collector.close()
        # Controlled direct engine write tests semantic integrity beyond the hash chain.
        recovered.engine._append("domain_outcome", o.model_copy(update={"id": "bad", "proof_sha256": "f" * 64}))
        with pytest.raises(ValueError, match="corrupt or unmatched"):
            recovered.verify()
    finally:
        recovered.close()
