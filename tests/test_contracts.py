import pytest
from neraium_poly.contracts import MarketSnapshot, ProbabilityEstimate
from pydantic import ValidationError


def test_roundtrip(market):
    assert MarketSnapshot.model_validate_json(market.model_dump_json()) == market


def test_reject_nonfinite(market):
    with pytest.raises(ValidationError):
        MarketSnapshot.model_validate({**market.model_dump(), "probability": float("nan")})


def test_interval(now):
    with pytest.raises(ValidationError):
        ProbabilityEstimate(
            timestamp=now,
            available_at=now,
            source="test",
            market_id="m1",
            token_id="t1",
            probability=0.5,
            lower=0.6,
            upper=0.9,
            model_id="x",
        )
