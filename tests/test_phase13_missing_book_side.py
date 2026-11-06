"""Regression for an observed live-cycle defect; these books are controlled fixtures."""
import pytest
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine
from test_experimental_strategies import frame, warm


@pytest.mark.parametrize("side", ["bids", "asks"])
@pytest.mark.parametrize("strategy", ["short_horizon", "persistent_relationship"])
def test_matured_forecast_rejects_missing_quote_side_without_aborting_other_work(side, strategy):
    engine = ExperimentalStrategyEngine(enabled=[strategy])
    warm(engine)
    original, now = frame(80, bid=0.45)
    invalid = original.books[0].model_copy(update={side: ()})
    changed = original.model_copy(update={"books": (invalid,)})
    signals = engine.evaluate_frame(changed, now)
    assert len(signals) == 1 and not signals[0].eligible
    assert "missing_liquidity" in signals[0].reasons
    assert signals[0].estimated_net_edge is None
    assert not engine.last_trace[strategy]["valid_observations"]
