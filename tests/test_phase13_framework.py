"""Controlled CLI/research orchestration boundaries, not genuine evidence."""
from datetime import UTC, datetime

import pytest
from neraium_poly.research.phase13 import framework


def test_research_rejects_unbounded_workers_and_existing_output(tmp_path):
    for workers in (0, 3, True):
        with pytest.raises(ValueError, match="one or two"):
            framework.run_sports_research(tmp_path, tmp_path, tmp_path / "out", workers=workers)
    with pytest.raises(ValueError, match="immutable"):
        framework.run_sports_research(tmp_path, tmp_path, tmp_path)


def test_failed_study_does_not_publish_success_manifest(tmp_path, monkeypatch):
    frame = tmp_path / "frame.json"
    frame.write_text('{}')

    def fail(*args):
        raise ValueError("controlled missing evidence")

    monkeypatch.setattr(framework, "_study", fail)
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="missing evidence"):
        framework.run_sports_research(tmp_path, frame, output, workers=1,
                                     cutoff=datetime(2026, 1, 1, tzinfo=UTC))
    assert not output.exists()
