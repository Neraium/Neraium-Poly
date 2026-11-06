"""Controlled research metadata fixtures; no operational prices/trades/performance."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase11.adaptive import ResearchRegistry
from neraium_poly.research.phase11.framework import load_summary, publish_summary, run_studies


def metric(value=0.02):
    return [
        {
            "model": "controlled-mark-model",
            "metric": "heldout_mae",
            "value": value,
            "baseline_value": 0.01,
            "sample_count": 10,
            "independent_events": 0,
        }
    ]


def test_registry_is_idempotent_drift_versioned_and_rollback_is_research_only(tmp_path):
    r = ResearchRegistry(tmp_path / "research.sqlite")
    now = datetime(2026, 11, 6, tzinfo=UTC)
    try:
        a = r.register(
            version_id="v1", dataset_sha256="a" * 64, available_at=now, metrics=metric(), provenance={}
        )
        assert (
            r.register(
                version_id="v1", dataset_sha256="a" * 64, available_at=now, metrics=metric(), provenance={}
            )
            == a
        )
        assert a["metrics"][0]["disposition"] == "suspended_worse_than_baseline"
        with pytest.raises(ValueError, match="reused"):
            r.register(
                version_id="v1",
                dataset_sha256="a" * 64,
                available_at=now,
                metrics=metric(0.03),
                provenance={},
            )
        with pytest.raises(ValueError, match="availability order"):
            r.register(
                version_id="past",
                dataset_sha256="a" * 64,
                available_at=now - timedelta(seconds=1),
                metrics=metric(),
                provenance={},
            )
        r.register(
            version_id="v2",
            dataset_sha256="b" * 64,
            available_at=now + timedelta(minutes=5),
            metrics=metric(0.03),
            provenance={},
        )
        assert r.status()["drift"][0]["error_change"] == pytest.approx(0.01)
        r.rollback("v1", reason="Controlled research rollback")
        s = r.status()
        assert s["selected_research_version"] == "v1" and s["versions"] == 2
        assert s["operational_effect"] is False and s["automatic_promotion"] is False
        assert all(not m["promotion_eligible"] for h in s["history"] for m in h["metrics"])
    finally:
        r.close()
    r = ResearchRegistry(tmp_path / "research.sqlite")
    assert r.status()["selected_research_version"] == "v1"
    r.close()


def test_registry_budget_and_invalid_metrics_fail_before_writes(tmp_path):
    r = ResearchRegistry(tmp_path / "research.sqlite", max_versions=1)
    now = datetime(2026, 11, 6, tzinfo=UTC)
    try:
        with pytest.raises(ValueError, match="nonnegative"):
            r.register(
                version_id="bad",
                dataset_sha256="a" * 64,
                available_at=now,
                metrics=metric(float("nan")),
                provenance={},
            )
        assert r.status()["versions"] == 0
        r.register(
            version_id="v1", dataset_sha256="a" * 64, available_at=now, metrics=metric(), provenance={}
        )
        with pytest.raises(ValueError, match="budget"):
            r.register(
                version_id="v2", dataset_sha256="b" * 64, available_at=now, metrics=metric(), provenance={}
            )
    finally:
        r.close()


def test_report_integrity_authority_and_missing_metrics_are_explicit(tmp_path):
    path = tmp_path / "latest.json"
    assert load_summary(path)["status"] == "unavailable"
    report = {
        "status": "controlled_fixture",
        "certification_authority": False,
        "automatic_promotion": False,
        "terminal_brier": None,
        "cost_adjusted_return": None,
    }
    publish_summary(path, report)
    assert load_summary(path) == report
    corrupt = json.loads(path.read_text())
    corrupt["report"]["cost_adjusted_return"] = 100
    path.write_text(json.dumps(corrupt))
    assert load_summary(path)["status"] == "unavailable"
    with pytest.raises(ValueError, match="authority"):
        publish_summary(path, {**report, "automatic_promotion": True})
    with pytest.raises(ValueError, match="bounded workers"):
        run_studies(tmp_path, workers=3)
