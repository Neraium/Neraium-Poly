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


def test_budget_checks_destination_ancestor_and_preserves_floor(tmp_path, monkeypatch):
    from collections import namedtuple

    from neraium_poly.research.phase11 import framework

    usage = namedtuple("Usage", "total used free")
    checked = []

    def disk_usage(path):
        checked.append(path)
        return usage(20 * 1024**3, 10 * 1024**3, 10 * 1024**3)

    monkeypatch.setattr(framework.shutil, "disk_usage", disk_usage)
    destination = tmp_path / "missing" / "nested" / "run"
    framework._budget(destination)
    assert checked == [tmp_path]
    assert not destination.exists()
    monkeypatch.setattr(framework.shutil, "disk_usage", lambda _: usage(10, 9, 1))
    with pytest.raises(ValueError, match="free-disk floor"):
        framework._budget(destination)


def test_registry_is_idempotent_drift_versioned_and_rollback_is_research_only(tmp_path):
    r = ResearchRegistry(tmp_path / "research.sqlite")
    now = datetime(2026, 11, 6, tzinfo=UTC)
    try:
        with pytest.raises(ValueError, match="another research coordinator"):
            ResearchRegistry(tmp_path / "research.sqlite")
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
        "generated_at": datetime.now(UTC).isoformat(),
        "certification_authority": False,
        "automatic_promotion": False,
        "terminal_brier": None,
        "cost_adjusted_return": None,
    }
    publish_summary(path, report)
    assert load_summary(path) == report
    generated = datetime.fromisoformat(report["generated_at"])
    assert load_summary(path, now=generated + timedelta(hours=2))["status"] == "stale"
    assert load_summary(path, now=generated - timedelta(seconds=1))["status"] == "unavailable"
    corrupt = json.loads(path.read_text())
    corrupt["report"]["cost_adjusted_return"] = 100
    path.write_text(json.dumps(corrupt))
    assert load_summary(path)["status"] == "unavailable"
    with pytest.raises(ValueError, match="authority"):
        publish_summary(path, {**report, "automatic_promotion": True})
    with pytest.raises(ValueError, match="bounded workers"):
        run_studies(tmp_path, workers=3)


def test_complete_experiment_uses_real_spawn_workers_and_preserves_nulls(tmp_path):
    # Controlled archive only: never copied into the operational research store.
    from neraium_poly.data import EventStore
    from neraium_poly.research.phase11.dataset import extract_dataset
    from neraium_poly.research.phase11.framework import run_experiment
    from test_phase11_micro import metadata, quote

    source = tmp_path / "fixture.sqlite"
    store = EventStore(source)
    try:
        store.append(metadata())
        for sec in range(0, 900, 10):
            store.append(quote(sec))
    finally:
        store.close()
    dataset = tmp_path / "dataset"
    extract_dataset(source, dataset, limit=100, min_free_bytes=0)
    output = tmp_path / "results" / "run"
    manifest = run_experiment(dataset=dataset, output=output, workers=2)
    assert 1 <= len(manifest["processes"]["actual_cpu_worker_pids"]) <= 2
    assert manifest["certification_authority"] is False and manifest["automatic_promotion"] is False
    report = load_summary(output.parent / "latest.json")
    assert report["independent_training_events"] == report["independent_heldout_events"] == 0
    assert len(report["strategies"]) == 6
    assert sum(s["research_status"] == "suspended_research" for s in report["strategies"]) == 4
    for name in ("microstructure", "models", "relationships"):
        assert (output / (name + ".json")).exists()
    with pytest.raises(ValueError, match="prior runs preserved"):
        run_experiment(dataset=dataset, output=output, workers=2)
