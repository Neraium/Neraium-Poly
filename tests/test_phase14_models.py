"""Controlled capability and probability-semantics regressions."""

import pytest
from neraium_poly.research.phase14.admission import assess_domain_opportunity
from neraium_poly.research.phase14.models import DomainModelAdapter, DomainModelRegistry, research_registry
from test_phase14_ledger import NOW, records


def test_registry_is_domain_specific_research_only():
    r = research_registry()
    assert set(r.status()) == {"weather", "crypto", "economics"}
    assert all(not value["trading_authority"] for value in r.status().values())
    unknown = DomainModelAdapter(
        "weather", "CONTROLLED", ("x",), ("input",), "v", lambda *a, **kw: {}, authorization="operational"
    )
    with pytest.raises(ValueError):
        DomainModelRegistry().register(unknown)


def test_scalar_probability_requires_containing_uncertainty():
    _m, _b, _c, _e, f = records()
    for update in [
        {"uncertainty": {"fixture": True}},
        {"uncertainty": {"lower_probability": 0.8, "upper_probability": 1}},
        {"probability_semantics": "outcome_distribution", "outcome_probabilities": {"yes": 0.6, "no": 0.4}},
    ]:
        with pytest.raises(ValueError):
            type(f).model_validate(f.model_copy(update=update).model_dump())


def test_research_model_never_acquires_order_authority_even_with_enable_flag():
    m, b, c, _e, f = records()
    for enabled in (True, False):
        result = assess_domain_opportunity(f, c, m, b, now=NOW, authorized=enabled)
        assert not result["eligible"] and not result["risk_evaluated"] and not result["order_attempted"]
        assert "domain_model_research_only" in result["reasons"]
        assert "terminal_domain_execution_capability_not_approved" in result["reasons"]
