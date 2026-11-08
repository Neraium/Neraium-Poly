"""Controlled quota/recovery checks; fixtures are not market observations."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from neraium_poly.data import segmented
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.ops.live_config import LivePaperConfig
from pydantic import ValidationError
from test_segmented_archive import managed, record

GIB = 1024**3


def test_persistent_service_configs_allocate_150_each_and_preserve_floor():
    root = Path(__file__).resolve().parents[1]
    for filename, schema in [('paper-live.example.json', LivePaperConfig),
                             ('experimental-paper.example.json', ExperimentalConfig)]:
        cfg = schema.model_validate_json((root/'config'/filename).read_text())
        assert cfg.archive_management_enabled
        assert cfg.archive_budget_mb*1024**2 == 150*GIB
        assert cfg.archive_reserve_disk_mb*1024**2 == 100*GIB
        assert cfg.archive_compression_enabled and cfg.archive_cold_verification_enabled


def test_experimental_schema_accepts_authorized_budget_but_no_larger_ceiling():
    assert ExperimentalConfig(archive_budget_mb=153600).archive_budget_mb == 153600
    with pytest.raises(ValidationError):
        ExperimentalConfig(archive_budget_mb=153601)


@pytest.mark.parametrize('previous_gib', [100, 200])
def test_quota_recovery_preserves_sealed_originals_and_duplicate_identity(tmp_path, previous_gib):
    path = tmp_path/'events.sqlite'
    store = managed(path, budget_bytes=previous_gib*GIB)
    try:
        for i in range(25):
            store.append(record(i))
        sealed = [r[0] for r in store.catalog.execute("SELECT name FROM segments WHERE status='sealed'")]
        assert sealed
        hashes = {name: hashlib.sha256((store.segment_dir/name).read_bytes()).hexdigest() for name in sealed}
    finally:
        store.close()
    recovered = managed(path, budget_bytes=150*GIB)
    try:
        assert recovered.count() == 25
        assert not recovered.append(record(24))
        assert recovered.status()['budget_bytes'] == 150*GIB
        assert all(hashlib.sha256((recovered.segment_dir/name).read_bytes()).hexdigest() == sha for name, sha in hashes.items())
    finally:
        recovered.close()


def test_reallocated_archive_still_fails_closed_below_global_floor(tmp_path, monkeypatch):
    store = managed(tmp_path/'events.sqlite', budget_bytes=150*GIB)
    try:
        store.append(record(0))
        store.min_free_bytes = 100*GIB
        monkeypatch.setattr(segmented.shutil, 'disk_usage', lambda _: SimpleNamespace(free=100*GIB-1))
        with pytest.raises(ValueError, match='archive_global_free_floor_reached'):
            store.append(record(1))
        assert store.count() == 1
    finally:
        store.close()
