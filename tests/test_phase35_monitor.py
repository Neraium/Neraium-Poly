"""Rendering fixtures, not market evidence."""
from neraium_poly.ops.monitor import _render_scorecard


def test_supplemental_native_counts_do_not_relabel_conditional_models():
    text = _render_scorecard({'independent_weather_research': {
        'forecasts': {'forecasts': 4},
        'native_evidence': {'native_verified_markets': 5, 'native_parent_events': 3}
    }}, 36, 18, []).plain
    assert 'New AWC forecasts 4' in text
    assert 'Native proofs 5 / parents 3' in text
    assert 'Conditional models: no market score' in text
    assert all(len(line) <= 36 for line in text.splitlines())
