"""Controlled fixtures only; these forecasts/outcomes never enter real paper accounts."""

import hashlib
import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase12.contracts import EventEvidence, EventForecast, VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import EventForecastLedger, content_sha256
from test_experimental_account import book, market

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


class Clock:
    now = NOW

    def __call__(self):
        return self.now


def evidence(ledger, clock, suffix=""):
    b, m = book(clock()), market(clock())
    records = []
    for kind, payload in [
        ("order_book", {"book": b.model_dump(mode="json")}),
        ("resolution_rules", {"market": m.model_dump(mode="json")}),
    ]:
        e = EventEvidence(
            id=kind + suffix,
            timestamp=clock(),
            available_at=clock(),
            source="CONTROLLED test fixture",
            event_id=m.event_id,
            market_id=m.market_id,
            kind=kind,
            content_sha256=content_sha256(payload),
            payload=payload,
        )
        ledger.record_evidence(e)
        records.append(e)
    f = EventForecast(
        id="forecast" + suffix,
        timestamp=clock(),
        available_at=clock(),
        source="CONTROLLED fixture",
        event_id=m.event_id,
        market_id=m.market_id,
        token_id=m.token_id,
        dependency_group=m.event_id,
        kind="market_baseline",
        probability=0.395,
        market_probability=0.395,
        evidence_cutoff=clock(),
        model_version="controlled-midpoint-v1",
        feature_version="controlled-book-v1",
        dataset_sha256="a" * 64,
        model_sha256="b" * 64,
        resolution_rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
        evidence_ids=tuple(e.id for e in records),
        uncertainty={"type": "uncalibrated_spread"},
    )
    return f, records


def outcome(f, clock):
    verification = {"controlled_test_proof": f.token_id, "payout": 1}
    return VerifiedEventOutcome(
        id="controlled-outcome",
        timestamp=clock(),
        available_at=clock(),
        source="CONTROLLED synthetic verifier fixture",
        event_id=f.event_id,
        market_id=f.market_id,
        token_id=f.token_id,
        payout=1,
        resolution_rules_sha256=f.resolution_rules_sha256,
        settled_at=NOW + timedelta(hours=1),
        verification_source="controlled-test-only",
        proof_sha256=content_sha256(verification),
        verification=verification,
    )


def test_baseline_immutable_idempotent_and_restart_safe(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path / "forecast", clock=clock)
    f, _records = evidence(ledger, clock)
    assert ledger.record_forecast(f)
    assert not ledger.record_forecast(f)
    assert ledger.forecasts() == (f,) and ledger.pending_forecasts() == (f,)
    with pytest.raises(ValueError, match="collision"):
        ledger.record_forecast(f.model_copy(update={"probability": 0.6}))
    with pytest.raises(sqlite3.IntegrityError, match="append only"):
        ledger.db.execute("UPDATE journal SET payload='{}'")
    head = ledger.verify()
    ledger.close()
    ledger = EventForecastLedger(tmp_path / "forecast", clock=clock)
    assert ledger.verify() == head
    s = ledger.summary()
    assert s["forecasts_pending"] == 1 and s["scores"]["brier"] is None
    assert s["independent_event_groups"] == 0 and not s["certification_authority"]
    ledger.close()


def test_exclusive_owner_and_record_budget(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock, max_records=2)
    with pytest.raises(ValueError, match="another event"):
        EventForecastLedger(tmp_path, clock=clock)
    f, _ = evidence(ledger, clock)
    with pytest.raises(ValueError, match="budget"):
        ledger.record_forecast(f)
    ledger.close()


def test_future_evidence_backdated_forecast_and_missing_rules_reject(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock)
    f, records = evidence(ledger, clock)
    with pytest.raises(ValueError, match="future or corrupt"):
        ledger.record_evidence(
            records[0].model_copy(update={"id": "future", "available_at": clock() + timedelta(seconds=1)})
        )
    with pytest.raises(ValueError, match="prospective"):
        ledger.record_forecast(
            f.model_copy(
                update={
                    "timestamp": clock() - timedelta(seconds=31),
                    "evidence_cutoff": clock() - timedelta(seconds=31),
                }
            )
        )
    with pytest.raises(ValueError, match="matching resolution"):
        ledger.record_forecast(f.model_copy(update={"evidence_ids": (records[0].id,)}))
    with pytest.raises(ValueError, match="mismatched"):
        ledger.record_forecast(f.model_copy(update={"evidence_cutoff": clock() - timedelta(seconds=1)}))
    with pytest.raises(ValueError, match="market baseline"):
        ledger.record_forecast(f.model_copy(update={"market_probability": 0.5}))
    ledger.close()


def test_baseline_cannot_claim_independent_probability_or_group_review(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock)
    f, _ = evidence(ledger, clock)
    with pytest.raises(ValueError, match="independent probability"):
        ledger.record_forecast(f.model_copy(update={"probability": 0.6}))
    with pytest.raises(ValueError, match="grouping review"):
        ledger.record_forecast(f.model_copy(update={"independence_reviewed": True}))
    with pytest.raises(ValueError, match="historical-frequency"):
        ledger.record_forecast(f.model_copy(update={"kind": "historical_frequency", "probability": 0.6}))
    ledger.close()


def test_independent_forecast_requires_external_evidence_and_trusted_model_validator(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock)
    f, _records = evidence(ledger, clock)
    model = f.model_copy(
        update={
            "kind": "independent_model",
            "probability": 0.7,
            "lower_probability": 0.6,
            "upper_probability": 0.8,
        }
    )
    with pytest.raises(ValueError, match="reviewed model"):
        ledger.record_forecast(model)
    e = EventEvidence(
        id="external",
        timestamp=clock(),
        available_at=clock(),
        source="https://api.weather.gov/controlled",
        event_id=f.event_id,
        market_id=f.market_id,
        kind="external_context",
        payload={"controlled": 1},
        content_sha256=content_sha256({"controlled": 1}),
        independent_of_market_price=True,
    )
    ledger.record_evidence(e)
    model = model.model_copy(update={"evidence_ids": (*f.evidence_ids, e.id)})
    with pytest.raises(ValueError, match="reviewed model"):
        ledger.record_forecast(model)
    ledger.independent_forecast_validator = lambda forecast, evidence: True  # Controlled reviewer only.
    assert ledger.record_forecast(model)
    ledger.close()


def test_outcome_json_flag_is_not_verified_proof_and_past_forecast_cannot_be_inserted(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock)
    f, _ = evidence(ledger, clock)
    ledger.record_forecast(f)
    clock.now = NOW + timedelta(hours=2)
    o = outcome(f, clock)
    with pytest.raises(ValueError, match="independent finalized"):
        ledger.record_outcome(o)
    ledger.outcome_validator = lambda proof: True  # Only synthetic verifier in this controlled test.
    assert ledger.record_outcome(o)
    s = ledger.summary()
    assert s["forecasts_resolved"] == 1 and s["independent_event_groups"] == 0
    assert s["scores"]["brier"] is None
    assert s["uncalibrated_resolved_scores"]["brier"] == pytest.approx((0.395 - 1) ** 2)
    f2, _ = evidence(ledger, clock, "-after")
    with pytest.raises(ValueError, match="known resolved"):
        ledger.record_forecast(f2)
    ledger.close()


def test_earliest_forecast_per_dependency_model_scores_once(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(
        tmp_path,
        clock=clock,
        independent_forecast_validator=lambda f, e: True,
        independence_validator=lambda f: True,
        outcome_validator=lambda o: True,
    )
    f, _ = evidence(ledger, clock)
    ext = EventEvidence(
        id="external",
        timestamp=clock(),
        available_at=clock(),
        source="https://weather.test.invalid",
        event_id=f.event_id,
        market_id=f.market_id,
        kind="external_context",
        payload={"fixture": 1},
        content_sha256=content_sha256({"fixture": 1}),
        independent_of_market_price=True,
    )
    ledger.record_evidence(ext)
    f = f.model_copy(
        update={
            "kind": "independent_model",
            "model_version": "controlled-model",
            "probability": 0.7,
            "lower_probability": 0.6,
            "upper_probability": 0.9,
            "independence_reviewed": True,
            "evidence_ids": (*f.evidence_ids, ext.id),
        }
    )
    ledger.record_forecast(f)
    clock.now += timedelta(seconds=1)
    f2, _ = evidence(ledger, clock, "-next")
    f2 = f2.model_copy(
        update={
            "kind": "independent_model",
            "model_version": "controlled-model",
            "probability": 0.8,
            "lower_probability": 0.6,
            "upper_probability": 0.9,
            "independence_reviewed": True,
            "evidence_ids": (*f2.evidence_ids, ext.id),
        }
    )
    ledger.record_forecast(f2)
    ledger.record_forecast(
        f2.model_copy(update={"id": "changed-model-hash", "model_sha256": "d" * 64, "probability": 0.6})
    )
    clock.now = NOW + timedelta(hours=2)
    ledger.record_outcome(outcome(f, clock))
    s = ledger.summary()
    assert s["forecasts_resolved"] == 3 and s["resolved_forecast_groups"] == 2
    assert s["scores"]["count"] == s["independent_event_groups"] == 1
    assert s["scores"]["brier"] == pytest.approx(0.09)
    assert len(s["model_scores"]) == 2
    assert all(m["count"] == 1 for m in s["model_scores"].values())
    assert ledger.summary(now=NOW)["forecasts_resolved"] == 0
    assert ledger.summary(now=NOW)["forecasts"] == 1
    ledger.close()


def test_tamper_detection_and_wrong_rule_outcome_not_scored(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock, outcome_validator=lambda o: True)
    f, _ = evidence(ledger, clock)
    ledger.record_forecast(f)
    clock.now = NOW + timedelta(hours=2)
    ledger.record_outcome(outcome(f, clock).model_copy(update={"resolution_rules_sha256": "f" * 64}))
    assert ledger.summary()["rejected_outcome_matches"] == 1
    assert ledger.summary()["forecasts_resolved"] == 0
    ledger.close()
    db = sqlite3.connect(tmp_path / "forecasts.sqlite")
    db.execute("DROP TRIGGER journal_no_update")
    db.execute("UPDATE journal SET payload='{}' WHERE seq=1")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="corrupt forecast"):
        EventForecastLedger(tmp_path, clock=clock)


def test_model_copy_cannot_bypass_forecast_field_validation(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock)
    f, _ = evidence(ledger, clock)
    with pytest.raises(ValueError):
        ledger.record_forecast(f.model_copy(update={"kind": "invented_independent_strategy"}))
    with pytest.raises(ValueError):
        ledger.record_forecast(f.model_copy(update={"probability": 1.5}))
    with pytest.raises(ValueError):
        ledger.record_forecast(f.model_copy(update={"certification_authority": True}))
    assert ledger.summary()["forecasts"] == 0
    ledger.close()


def test_independent_forecast_baseline_uses_same_immutable_quote_cutoff(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(
        tmp_path,
        clock=clock,
        outcome_validator=lambda o: True,
        independence_validator=lambda f: True,
        independent_forecast_validator=lambda f, e: True,
    )
    baseline, _ = evidence(ledger, clock)
    ledger.record_forecast(baseline.model_copy(update={"independence_reviewed": True}))
    clock.now += timedelta(seconds=1)
    # Second actual controlled quote has a different market-implied probability.
    b = book(clock(), bid=0.49, ask=0.5)
    m = market(clock())
    ids = []
    for kind, payload in [
        ("order_book", {"book": b.model_dump(mode="json")}),
        ("resolution_rules", {"market": m.model_dump(mode="json")}),
        ("external_context", {"controlled": 1}),
    ]:
        e = EventEvidence(
            id="new-" + kind,
            timestamp=clock(),
            available_at=clock(),
            source="https://external.test.invalid",
            event_id=baseline.event_id,
            market_id=baseline.market_id,
            kind=kind,
            payload=payload,
            content_sha256=content_sha256(payload),
            independent_of_market_price=kind == "external_context",
        )
        ledger.record_evidence(e)
        ids.append(e.id)
    f = baseline.model_copy(
        update={
            "id": "independent-later",
            "timestamp": clock(),
            "available_at": clock(),
            "evidence_cutoff": clock(),
            "kind": "independent_model",
            "probability": 0.7,
            "market_probability": 0.495,
            "lower_probability": 0.6,
            "upper_probability": 0.8,
            "independence_reviewed": True,
            "model_version": "controlled-model-v2",
            "evidence_ids": tuple(ids),
            "horizon_seconds": 3600,
        }
    )
    ledger.record_forecast(f)
    clock.now = NOW + timedelta(hours=2)
    ledger.record_outcome(outcome(f, clock))
    s = ledger.summary()
    assert s["baseline_scores"]["brier"] == pytest.approx((0.495 - 1) ** 2)
    assert s["standalone_baseline_scores"]["brier"] == pytest.approx((0.395 - 1) ** 2)
    assert s["scores"]["market_brier"] == s["baseline_scores"]["brier"]
    assert s["category_progress"]["Unknown"] == {"forecasts": 2, "pending": 0, "resolved": 2}
    assert s["category_scores"]["Unknown"]["count"] == s["horizon_scores"]["under_24h"]["count"] == 1
    assert s["rolling_calibration"]["count"] == 1
    ledger.close()


def test_verified_market_resolution_blocks_complementary_token_forecasts(tmp_path):
    clock = Clock()
    ledger = EventForecastLedger(tmp_path, clock=clock, outcome_validator=lambda o: True)
    original, _ = evidence(ledger, clock)
    ledger.record_forecast(original)
    clock.now = NOW + timedelta(hours=2)
    ledger.record_outcome(outcome(original, clock))
    # A fresh quote for a different token cannot reopen the verified settled market.
    b = book(clock()).model_copy(update={"token_id": "controlled-complement"})
    m = market(clock()).model_copy(update={"token_id": "controlled-complement"})
    ids = []
    for kind, payload in [
        ("order_book", {"book": b.model_dump(mode="json")}),
        ("resolution_rules", {"market": m.model_dump(mode="json")}),
    ]:
        e = EventEvidence(
            id="complement-" + kind,
            timestamp=clock(),
            available_at=clock(),
            source="CONTROLLED fixture",
            event_id=original.event_id,
            market_id=original.market_id,
            kind=kind,
            payload=payload,
            content_sha256=content_sha256(payload),
        )
        ledger.record_evidence(e)
        ids.append(e.id)
    complement = original.model_copy(
        update={
            "id": "complement-forecast",
            "timestamp": clock(),
            "available_at": clock(),
            "evidence_cutoff": clock(),
            "token_id": b.token_id,
            "evidence_ids": tuple(ids),
        }
    )
    with pytest.raises(ValueError, match="known resolved"):
        ledger.record_forecast(complement)
    assert len(ledger.forecasts()) == 1
    ledger.close()


@pytest.mark.parametrize(
    "filename",
    [
        "forecast.lock",
        "forecasts.sqlite",
        "forecasts.sqlite-wal",
        "forecasts.sqlite-shm",
        "other-evidence.json",
    ],
)
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_nested_forecast_file_aliases_reject_before_any_mutation(tmp_path, filename, link_kind):
    certified = tmp_path / "certified"
    certified.mkdir()
    sentinel = certified / "risk.sqlite"
    sentinel.write_bytes(b"CONTROLLED certified account sentinel; do not mutate")
    before = sentinel.read_bytes()
    directory = tmp_path / "experimental" / "event-forecasts"
    directory.mkdir(parents=True)
    alias = directory / filename
    if link_kind == "symlink":
        alias.symlink_to(sentinel)
    else:
        os.link(sentinel, alias)
    entries_before = sorted(p.name for p in directory.iterdir())
    with pytest.raises(ValueError, match="storage aliases"):
        EventForecastLedger(directory, clock=Clock())
    assert sentinel.read_bytes() == before
    assert sorted(p.name for p in directory.iterdir()) == entries_before
