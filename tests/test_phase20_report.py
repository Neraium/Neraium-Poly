"""Controlled archive reporting; fixture forecasts are not empirical evidence."""
import pytest
from neraium_poly.research.phase20.report import evaluate_archive


def test_replay_report_withholds_scores_without_independent_outcomes(monkeypatch, tmp_path):
    import neraium_poly.research.phase20.report as module
    from test_phase19_qualification import ASOF, HELD_START, TRAIN_END, fixtures
    original, _label = fixtures()
    class Archive:
        def __init__(self, *_a, **_kw): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass
        def latest(self, kind, _limit): return [original] if kind == 'EventProbabilityStudy' else []
        def _catalog_rows(self, *_a): return [{'n': 1}]
    monkeypatch.setattr(module, 'ReadonlyArchive', Archive)
    result = evaluate_archive(tmp_path, training_end=TRAIN_END, heldout_start=HELD_START, as_of=ASOF)
    assert result['counts']['original_forecasts'] == result['matured_forecasts'] == 1
    assert result['counts']['verified_outcome_forecasts'] == 0
    assert result['qualified_training_events'] == result['qualified_heldout_events'] == 0
    assert result['sii_comparison']['brier_improvement'] is None
    assert not result['sii_comparison']['sii_in_trading_path']
    assert not result['trading_authority'] and not result['certification_authority']


@pytest.mark.parametrize('limit', [0, -1, 1001, True])
def test_unbounded_report_query_rejected(tmp_path, limit):
    with pytest.raises(ValueError, match='bounded'):
        evaluate_archive(tmp_path, training_end=None, heldout_start=None, limit=limit)


def test_malformed_context_preserves_rejection_instead_of_crashing_report(monkeypatch, tmp_path):
    import neraium_poly.research.phase20.report as module
    from test_phase19_qualification import ASOF, HELD_START, TRAIN_END, fixtures
    original, _label = fixtures()
    original['market']['end_time'] = None
    class Archive:
        def __init__(self, *_a, **_kw): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass
        def latest(self, kind, _limit): return [original] if kind == 'EventProbabilityStudy' else []
        def _catalog_rows(self, *_a): return [{'n': 1}]
    monkeypatch.setattr(module, 'ReadonlyArchive', Archive)
    result = evaluate_archive(tmp_path, training_end=TRAIN_END, heldout_start=HELD_START, as_of=ASOF)
    assert result['matured_forecasts'] == 0 and result['rejections']
