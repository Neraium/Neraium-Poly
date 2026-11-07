"""Controlled source/label fixtures; no genuine resolved-event claims."""
from test_phase19_qualification import evaluate, fixtures


def test_unresolved_first_forecast_cannot_be_replaced_by_later_resolved_update():
    first, _unused = fixtures(parent='CONTROLLED shared')
    second, resolved = fixtures(1, parent='CONTROLLED shared')
    r = evaluate([first, second, resolved], reviewed=True)
    assert r['counts']['verified_outcome_forecasts'] == 1
    assert r['qualified_training_events'] == r['qualified_heldout_events'] == 0
    assert r['rejections']['earliest_prospective_group_forecast_outcome_pending'] == 1
    assert not r['calibration_rows']


def test_pending_training_exposure_prevents_false_disjoint_heldout():
    first, _unused = fixtures(parent='CONTROLLED shared')
    second, resolved = fixtures(heldout=True, parent='CONTROLLED shared')
    r = evaluate([first, second, resolved], reviewed=True)
    assert r['qualified_heldout_events'] == 0 and not r['calibration_rows']


def test_verified_earliest_keeps_existing_group_dedup_and_counts():
    first, a = fixtures(parent='CONTROLLED shared')
    second, b = fixtures(1, parent='CONTROLLED shared')
    result = evaluate([second, b, first, a], reviewed=True)
    assert result['qualified_training_events'] == 1
    assert result['validation']['cohorts'][0]['calibration']['rejections']['repeated_dependency_group'] == 1


def test_parent_dependency_ambiguity_is_not_hidden_by_missing_labels():
    first, _unused = fixtures(parent='CONTROLLED shared')
    second, resolved = fixtures(1, parent='CONTROLLED shared')
    result = evaluate([first, second, resolved], reviewed=True,
        review_group=lambda s: {'reviewed': True, 'dependency_group': s['forecast']['id']})
    assert not result['calibration_rows'] and result['rejections']['same_parent_has_inconsistent_dependency_groups'] == 1
