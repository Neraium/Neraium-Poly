"""Controlled domain research state/failure tests; no genuine observations claimed."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.runtime import DomainResearchRuntime
from test_phase14_ledger import NOW, records


def test_low_disk_keeps_legacy_counts_and_creates_no_journal(tmp_path, monkeypatch):
    r = DomainResearchRuntime(tmp_path / "domains", clock=lambda: NOW)
    monkeypatch.setattr(r, "_storage_ready", lambda: False)
    with pytest.raises(ValueError, match="8GiB"):
        r._open()
    assert not (tmp_path / "domains").exists()
    s = r.summary(
        legacy_sports={"ternary_research_forecasts": 2, "ternary_pending": 2, "ternary_resolved": 0}
    )
    assert s["status"] == "storage_blocked" and s["domains"]["sports"]["independent_forecasts"] == 2
    assert s["ledger"]["forecasts"] == 0 and s["trading_authority"] is False


def test_existing_history_under_low_disk_is_unknown_not_false_zero(tmp_path, monkeypatch):
    r = DomainResearchRuntime(
        tmp_path / "domains", clock=lambda: NOW, state={"anchor": {"records": 3, "head_sha256": "a" * 64}}
    )
    monkeypatch.setattr(r, "_storage_ready", lambda: False)
    s = r.summary()
    assert s["ledger"]["forecasts"] is None
    assert s["domains"]["crypto"]["independent_forecasts"] is None
    assert r.checkpoint()["anchor"]["records"] == 3


def test_degraded_frame_classifies_cache_but_never_claims_fresh_quotes(tmp_path, monkeypatch):
    r = DomainResearchRuntime(tmp_path / "domains", clock=lambda: NOW)
    monkeypatch.setattr(r, "_storage_ready", lambda: False)
    m, b, _c, _e, _f = records()
    f = SharedMarketFrame(
        timestamp=NOW,
        available_at=NOW,
        source="CONTROLLED",
        markets=(m,),
        books=(b,),
        producer_health={"status": "degraded"},
    )
    r.on_frame(f, NOW)
    s = r.summary()
    assert s["markets_monitored"] == 1 and s["market_source_status"] == "degraded_cached_universe"
    assert sum(v["fresh_markets"] for v in s["domains"].values()) == 0
    assert r.ledger is None and not (tmp_path / "domains").exists()


async def test_storage_guard_prevents_network_sources(tmp_path, monkeypatch):
    r = DomainResearchRuntime(tmp_path / "domains", clock=lambda: NOW)
    monkeypatch.setattr(r, "_storage_ready", lambda: False)
    await r.refresh()
    assert r.totals["source_attempts"] == 0 and r.ledger is None
    assert r.last_error == "domain_durable_storage_below_8GiB_floor"


def test_failed_relationship_restore_preserves_prior_checkpoint(tmp_path):
    previous = {"CONTROLLED_invalid": "preserved"}
    r = DomainResearchRuntime(tmp_path / "domains", clock=lambda: NOW, state={"relationships": previous})
    try:
        with pytest.raises(ValueError):
            r._open()
        assert r.relationships is None
        assert r.checkpoint()["relationships"] == previous
        with pytest.raises(ValueError):
            r._open()
    finally:
        r.close()


def test_model_replay_rejects_forged_calibration_label(tmp_path, monkeypatch):
    import neraium_poly.research.phase14.runtime as module

    m, _b, c, e, f = records()
    r = DomainResearchRuntime(tmp_path / "domains", clock=lambda: NOW)
    mapper = lambda market, now: c
    monkeypatch.setattr(module, "adapter", lambda d: (mapper, None, None))
    result = {
        "status": "research_estimate",
        "probability": f.probability,
        "model_sha256": f.model_sha256,
        "dataset_sha256": f.dataset_sha256,
        "feature_version": f.feature_version,
        "model_version": f.model_version,
        "uncertainty": f.uncertainty,
        "calibration_status": "unvalidated_research",
    }
    r.registry.models["weather"] = SimpleNamespace(forecast=lambda *a, **k: result)
    assert r._replay_forecast(f, c, m, (e,)) is True
    assert (
        r._replay_forecast(f.model_copy(update={"calibration_status": "independently_validated"}), c, m, (e,))
        is False
    )


async def test_unsupported_domain_result_never_calls_native_acquisition(tmp_path, monkeypatch):
    from neraium_poly.research.phase14.ledger import UniversalForecastLedger
    from neraium_poly.research.phase14.outcomes import DomainOutcomeCollector

    now = [NOW]
    m, b, c, e, f = records()
    ledger = UniversalForecastLedger(tmp_path / "d", clock=lambda: now[0], forecast_validator=lambda *a: True)
    ledger.record_evidence(e)
    ledger.record_forecast(f, contract=c, market=m, book=b)
    collector = DomainOutcomeCollector(ledger, clock=lambda: now[0])
    now[0] += timedelta(days=2)

    async def forbidden(*a, **kw):
        raise AssertionError("unsupported source must not request proof")

    monkeypatch.setattr("neraium_poly.research.phase12.outcome_collector.acquire_verified_outcome", forbidden)
    try:
        await collector.check_pending()
        assert collector.state["checks"] == 0
        assert collector.state["last_error"] == "independent_domain_outcome_source_not_qualified"
        assert not ledger.outcomes()
    finally:
        collector.close()
        ledger.close()
