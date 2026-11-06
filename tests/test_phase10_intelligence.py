"""Controlled relationship fixtures, never real-market opportunity evidence."""

from datetime import timedelta

from neraium_poly.experimental.intelligence import ExperimentalRelationshipIntelligence
from test_experimental_strategies import frame


def pair(i, left=0.4, right=0.4):
    a, now = frame(i, bid=left, token="t1", market="m1")
    b, _ = frame(i, bid=right, token="t2", market="m2")
    return {"t1": a.markets[0], "t2": b.markets[0]}, {"t1": a.books[0], "t2": b.books[0]}, now


def state(engine):
    return engine.checkpoint()["engine"]["states"][0]


def baseline(engine):
    for i in range(20):
        markets, books, now = pair(i)
        engine.observe(markets, books, now)
    return markets, books, now


def test_transient_missing_leg_preserves_baseline_without_observing_metadata_probability():
    engine = ExperimentalRelationshipIntelligence()
    baseline(engine)
    prior = state(engine)
    markets, books, now = pair(20, left=0.6)
    # Metadata probabilities deliberately disagree with observed midpoint.
    assert markets["t1"].probability == 0.99
    assert engine.observe(markets, {"t1": books["t1"]}, now) == ()
    assert state(engine) == prior
    assert engine.status()["relationships"] == 1
    assert engine.status()["evaluations"] == 0
    restored = ExperimentalRelationshipIntelligence()
    restored.restore(engine.checkpoint())
    (evidence,) = restored.observe(markets, books, now)
    assert evidence.sample_count == 21
    assert evidence.persistence == 1
    assert not evidence.qualified
    assert state(restored)["baseline"] == prior["baseline"]


def test_stale_incomplete_and_mismatched_current_legs_never_emit_evidence():
    engine = ExperimentalRelationshipIntelligence()
    baseline(engine)
    previous = state(engine)
    markets, books, now = pair(20)
    for bad in (
        books["t2"].model_copy(update={"complete": False}),
        books["t2"].model_copy(update={"timestamp": now - timedelta(seconds=16)}),
        books["t2"].model_copy(update={"market_id": "unrelated"}),
    ):
        assert engine.observe(markets, {"t1": books["t1"], "t2": bad}, now) == ()
        assert state(engine) == previous


def test_long_gap_resets_persistence_but_preserves_existing_baseline_semantics():
    engine = ExperimentalRelationshipIntelligence()
    baseline(engine)
    for i in (20, 21):
        markets, books, now = pair(i, left=0.6)
        (evidence,) = engine.observe(markets, books, now)
    assert evidence.persistence == 2
    baseline_before = state(engine)["baseline"]
    markets, books, now = pair(22, left=0.6)
    assert engine.observe(markets, {}, now) == ()
    markets, books, now = pair(35, left=0.6)
    (evidence,) = engine.observe(markets, books, now)
    assert evidence.persistence == 1 and not evidence.qualified
    assert state(engine)["baseline"] == baseline_before
    assert state(engine)["samples"] == 23


def test_metadata_universe_eviction_and_bounded_pair_membership():
    engine = ExperimentalRelationshipIntelligence(max_relationships=1)
    markets, books, now = baseline(engine)
    # Missing books retains state; removed metadata evicts state.
    engine.observe(markets, {}, now)
    assert len(engine.checkpoint()["engine"]["states"]) == 1
    engine.observe({"t1": markets["t1"]}, books, now)
    assert engine.checkpoint()["definitions"] == []
    assert engine.checkpoint()["engine"]["states"] == []
    third, _ = frame(20, bid=0.4, token="t3", market="m3")
    markets, books, now = pair(20)
    markets["t3"], books["t3"] = third.markets[0], third.books[0]
    engine.observe(markets, books, now)
    assert len(engine.checkpoint()["definitions"]) == 1
    assert len(engine.checkpoint()["engine"]["states"]) == 1
