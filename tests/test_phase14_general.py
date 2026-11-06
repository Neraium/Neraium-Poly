"""Unstructured event evidence cannot manufacture calibrated probabilities."""
from datetime import timedelta

import pytest
from neraium_poly.research.phase14 import general
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.finance import digest
from test_phase14_finance import NOW, market


def evidence():
    p={"CONTROLLED":"fixture official announcement"}
    return DomainEvidence(id="fixture",timestamp=NOW,available_at=NOW,retrieved_at=NOW,
        source="https://www.nasa.gov",domain="science",provider="CONTROLLED",source_id="fixture",
        content_sha256=digest(p),payload=p,independent_of_polymarket=True,qualification="qualified_research")


def test_general_interpretation_and_numerical_estimates_fail_closed_without_review():
    c=general.map_general(market(),domain="science",now=NOW)
    assert c.review_required and not c.compatible
    result=general.qualify_general_evidence(c,[evidence()],cutoff=NOW)
    assert not result["evidence_ids"] and not result["numerical_probability_supported"]
    assert general.forecast_general(c,[evidence()],cutoff=NOW)["probability"] is None


def test_reviewed_general_evidence_stays_non_numerical_and_future_data_rejects():
    c=general.map_general(market(),domain="science",now=NOW)
    e=evidence()
    assert general.qualify_general_evidence(c,[e],cutoff=NOW,reviewer=lambda c,e:True)["evidence_ids"]==[e.id]
    changed=e.model_copy(update={"available_at": NOW+timedelta(seconds=1)})
    assert not general.qualify_general_evidence(c,[changed],cutoff=NOW,reviewer=lambda c,e:True)["evidence_ids"]


def test_news_and_other_domain_cannot_silently_become_validated_science_context():
    c=general.map_general(market(),domain="science",now=NOW)
    e=evidence().model_copy(update={"domain":"politics"})
    assert not general.qualify_general_evidence(c,[e],cutoff=NOW,reviewer=lambda c,e:True)["evidence_ids"]
    with pytest.raises(ValueError):general.map_general(market(),domain="sports",now=NOW)
