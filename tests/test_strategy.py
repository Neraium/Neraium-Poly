from datetime import timedelta

import pytest
from neraium_poly.contracts import PriceLevel, RelationshipEvidence
from neraium_poly.strategy import (
    HistogramCalibrator,
    LabeledForecast,
    ModelRegistry,
    OpportunityRanker,
    ProtocolFeeModel,
    walk_forward,
)


def labels(now, n=100, probability=0.4):
    rows = []
    for i in range(n):
        at = now - timedelta(days=10, seconds=-i)
        rows.append(
            LabeledForecast(
                id=f"label{i}",
                timestamp=at,
                available_at=at,
                source="synthetic-label",
                market_id=f"historical{i}",
                event_id=f"event{i}",
                probability=probability,
                outcome=int(i % 10 < 9),
                label_available_at=at + timedelta(hours=1),
                executable_price=0.4,
                executable_quantity=100,
                protocol_fee_rate=0.02,
            )
        )
    return rows


def qualified(now):
    return RelationshipEvidence(
        id="evidence",
        timestamp=now,
        available_at=now,
        source="independent-source-one",
        relationship_id="rel",
        sample_count=50,
        persistence=5,
        strength=4,
        confidence=0.9,
        qualified=True,
        observation_ids=("obs-one", "obs-two"),
        regime="persistent_relationship_shift",
    )


def approved(now, market):
    model = HistogramCalibrator.fit(labels(now), now - timedelta(hours=1))
    registry = ModelRegistry()
    mid = registry.register(model)
    provenance = registry.approve(mid, "research-reviewer", now - timedelta(minutes=1))
    estimate = registry.estimate(mid, market, now, ("evidence",))
    return model, registry, provenance, estimate


def test_calibration_causal_uncertainty_and_explicit_approval(now, market):
    model = HistogramCalibrator.fit(labels(now), now - timedelta(hours=1))
    registry = ModelRegistry()
    mid = registry.register(model)
    assert not model.provenance.approved and registry.active_id is None
    with pytest.raises(ValueError, match="approved"):
        registry.estimate(mid, market, now)
    provenance = registry.approve(mid, "reviewer", now)
    estimate = registry.estimate(mid, market, now)
    assert provenance.approved and not model.provenance.approved
    assert estimate.calibrated and 0.8 < estimate.lower < estimate.probability < estimate.upper < 1
    assert estimate.model_id == model.provenance.id
    assert registry.audit[-1]["actor"] == "reviewer"


def test_future_labels_excluded_and_duplicates_rejected(now):
    rows = labels(now)
    extra = rows[0].model_copy(
        update={
            "id": "future",
            "event_id": "future",
            "label_available_at": now + timedelta(days=1),
            "outcome": 0,
        }
    )
    assert HistogramCalibrator.fit(rows + [extra], now) == HistogramCalibrator.fit(rows, now)
    with pytest.raises(ValueError, match="duplicate"):
        HistogramCalibrator.fit(rows + [rows[0]], now)
    with pytest.raises(ValueError, match="correlated"):
        HistogramCalibrator.fit(rows + [rows[0].model_copy(update={"id": "different"})], now)
    with pytest.raises(ValueError, match="no labels"):
        HistogramCalibrator.fit([extra], now)


def test_sparse_bin_uncertainty_not_calibrated(now, market):
    model = HistogramCalibrator.fit(labels(now, 10), now - timedelta(hours=1), min_samples=30)
    estimate = model.estimate(market, now)
    assert not estimate.calibrated
    assert estimate.upper - estimate.lower > 0.3
    with pytest.raises(ValueError, match="samples"):
        registry = ModelRegistry()
        registry.approve(registry.register(model), "reviewer", now)


def test_model_versions_and_rollback(now, market):
    first = HistogramCalibrator.fit(labels(now), now - timedelta(hours=2))
    second = HistogramCalibrator.fit(labels(now, 110), now - timedelta(hours=1))
    registry = ModelRegistry()
    one, two = registry.register(first), registry.register(second)
    registry.approve(one, "a", now - timedelta(minutes=2))
    registry.approve(two, "a", now - timedelta(minutes=1))
    with pytest.raises(ValueError):
        registry.estimate(one, market, now)
    registry.rollback(one, "b", now)
    assert registry.estimate(one, market, now).model_id == one
    assert registry.audit[-1]["action"] == "rollback"
    with pytest.raises(ValueError):
        registry.rollback("unknown", "b", now)


def test_approval_cannot_be_applied_to_past(now, market):
    _, registry, provenance, _ = approved(now, market)
    old = now - timedelta(minutes=2)
    with pytest.raises(ValueError, match="approval"):
        registry.estimate(
            provenance.id, market.model_copy(update={"available_at": old, "timestamp": old}), old
        )


def test_fee_curve_symmetry_and_maker():
    fee = ProtocolFeeModel(0.07)
    assert fee.fee_per_share(0.3) == pytest.approx(fee.fee_per_share(0.7))
    assert 100 * fee.fee_per_share(0.4) == pytest.approx(1.68)
    assert ProtocolFeeModel(0.07, maker=True).fee_per_share(0.4) == 0
    with pytest.raises(ValueError):
        ProtocolFeeModel(float("nan"))


def test_opportunity_lower_bound_ev_and_fee_accounting(now, market, book):
    _, _, provenance, estimate = approved(now, market)
    ranker = OpportunityRanker()
    result = ranker.rank(
        market, book, estimate, [qualified(now)], provenance, now, fee_model=ProtocolFeeModel(0.02)
    )
    assert result and result.side == "BUY"
    assert result.fee_rate == pytest.approx(0.02)
    assert result.net_edge == pytest.approx(estimate.lower - 0.4 - 0.02 * 0.4 - 0.005)
    assert result.conservative_probability == estimate.lower
    assert result.independent_evidence == 1
    assert result.liquidity == 100  # executable outcome shares, not dollars
    assert not ranker.last_reasons


@pytest.mark.parametrize(
    "case,reason",
    [
        ("stale", "stale_input"),
        ("rules", "unverified_active_settlement"),
        ("uncertain", "excessive_model_uncertainty"),
        ("unapproved", "unapproved_model"),
        ("uncalibrated", "uncalibrated_estimate"),
        ("evidence", "unqualified_evidence"),
        ("spread", "wide_spread"),
        ("liquidity", "insufficient_executable_liquidity"),
        ("fees", "unknown_fee_schedule"),
        ("maker", "maker_fee_incompatible_with_taker_quote"),
        ("future", "future_input"),
        ("contradictory", "net_value_below_uncertainty_adjusted_threshold"),
    ],
)
def test_ranker_suppresses_unsafe_inputs(now, market, book, case, reason):
    _, _, provenance, estimate = approved(now, market)
    evidence = [qualified(now)]
    fee = ProtocolFeeModel(0.02)
    if case == "stale":
        book = book.model_copy(update={"timestamp": now - timedelta(seconds=31)})
    elif case == "rules":
        market = market.model_copy(update={"resolution_rules": ""})
    elif case == "uncertain":
        estimate = estimate.model_copy(update={"lower": 0.1, "upper": 1})
    elif case == "unapproved":
        provenance = provenance.model_copy(update={"approved": False})
    elif case == "uncalibrated":
        estimate = estimate.model_copy(update={"calibrated": False})
    elif case == "evidence":
        evidence = [evidence[0].model_copy(update={"qualified": False})]
    elif case == "spread":
        book = book.model_copy(update={"bids": (PriceLevel(price=0.1, size=100),)})
    elif case == "liquidity":
        book = book.model_copy(update={"asks": (PriceLevel(price=0.4, size=1),)})
    elif case == "fees":
        fee = None
    elif case == "maker":
        fee = ProtocolFeeModel(0.02, maker=True)
    elif case == "future":
        estimate = estimate.model_copy(update={"available_at": now + timedelta(seconds=1)})
    elif case == "contradictory":
        estimate = estimate.model_copy(update={"probability": 0.2, "lower": 0.15, "upper": 0.3})
    ranker = OpportunityRanker()
    assert ranker.rank(market, book, estimate, evidence, provenance, now, fee_model=fee) is None
    assert reason in ranker.last_reasons


def test_exceptional_independence_requires_distinct_support(now, market, book):
    _, _, provenance, estimate = approved(now, market)
    ranker = OpportunityRanker()
    first = qualified(now)
    second = first.model_copy(update={"id": "evidence-two", "source": "source-two"})
    estimate = estimate.model_copy(update={"evidence_ids": ("evidence", "evidence-two")})
    assert (
        ranker.rank(
            market,
            book,
            estimate,
            [first, second],
            provenance,
            now,
            fee_model=ProtocolFeeModel(0.02),
            tier="exceptional",
        )
        is None
    )
    second = second.model_copy(update={"observation_ids": ("other-one", "other-two")})
    result = ranker.rank(
        market,
        book,
        estimate,
        [first, second],
        provenance,
        now,
        fee_model=ProtocolFeeModel(0.02),
        tier="exceptional",
    )
    assert result and result.independent_evidence == 2


def test_depth_quote_and_slippage(now, market, book):
    _, _, provenance, estimate = approved(now, market)
    book = book.model_copy(update={"asks": (PriceLevel(price=0.4, size=5), PriceLevel(price=0.42, size=10))})
    result = OpportunityRanker().rank(
        market, book, estimate, [qualified(now)], provenance, now, fee_model=ProtocolFeeModel(0.02)
    )
    assert result and result.market_probability == 0.42
    assert result.slippage == pytest.approx(0.02)
    book = book.model_copy(update={"asks": (PriceLevel(price=0.4, size=5), PriceLevel(price=0.45, size=10))})
    assert (
        OpportunityRanker().rank(
            market, book, estimate, [qualified(now)], provenance, now, fee_model=ProtocolFeeModel(0.02)
        )
        is None
    )


def test_walk_forward_reproducible_and_no_label_leakage(now):
    rows = labels(now, 100)
    # Ensure historical outcomes settle between sequential decisions.
    rows = [
        row.model_copy(
            update={
                "timestamp": now - timedelta(days=200 - i),
                "available_at": now - timedelta(days=200 - i),
                "label_available_at": now - timedelta(days=200 - i) + timedelta(hours=1),
            }
        )
        for i, row in enumerate(rows)
    ]
    result = walk_forward(rows, now)
    assert result == walk_forward(list(reversed(rows)), now)
    assert result.performance.brier_score is not None
    assert result.performance.trades > 0 and result.performance.realized_pnl == 0
    assert result.performance.out_of_sample
    by_id = {r.id: r for r in rows}
    for prediction in result.predictions:
        decision = by_id[prediction["record_id"]]
        for training_id in prediction["training_ids"]:
            assert by_id[training_id].label_available_at < decision.available_at
            assert by_id[training_id].event_id != decision.event_id
    future = rows[-1].model_copy(
        update={"id": "unsettled", "event_id": "unsettled", "label_available_at": now + timedelta(days=1)}
    )
    additional = walk_forward(rows + [future], now)
    assert additional.excluded_unsettled == 1
    assert additional.performance.simulated_pnl == result.performance.simulated_pnl


def test_backtest_losing_streak_has_drawdown_and_no_recovery_sizing(now):
    rows = labels(now, 80)
    rows = [
        row.model_copy(
            update={
                "timestamp": now - timedelta(days=200 - i),
                "available_at": now - timedelta(days=200 - i),
                "outcome": int(i < 65),
                "label_available_at": now - timedelta(days=200 - i) + timedelta(hours=1),
            }
        )
        for i, row in enumerate(rows)
    ]
    result = walk_forward(rows, now)
    losses = [p["simulated_pnl"] for p in result.predictions if p["simulated_pnl"] < 0]
    assert losses and all(p == pytest.approx(-2) for p in losses)
    assert result.performance.max_drawdown > 0


def test_ranker_cross_exchange_and_expired_market_rejected(now, market, book):
    _, _, provenance, estimate = approved(now, market)
    ranker = OpportunityRanker()
    other = book.model_copy(update={"exchange": "other"})
    assert (
        ranker.rank(
            market, other, estimate, [qualified(now)], provenance, now, fee_model=ProtocolFeeModel(0.02)
        )
        is None
    )
    assert "exchange_mismatch" in ranker.last_reasons
    expired = market.model_copy(update={"end_time": now - timedelta(seconds=1)})
    assert (
        ranker.rank(
            expired, book, estimate, [qualified(now)], provenance, now, fee_model=ProtocolFeeModel(0.02)
        )
        is None
    )
    assert "market_expired_or_invalid_end_time" in ranker.last_reasons


def test_multilevel_fee_bound_covers_all_price_improvements(now, market, book):
    _, _, provenance, estimate = approved(now, market)
    book = book.model_copy(update={"asks": (PriceLevel(price=0.4, size=5), PriceLevel(price=0.42, size=10))})
    fee = ProtocolFeeModel(0.02)
    result = OpportunityRanker().rank(
        market, book, estimate, [qualified(now)], provenance, now, fee_model=fee
    )
    assert result and result.fee_rate == 0.02
    for price in (0.001, 0.1, 0.4, 0.42, 0.9):
        assert price * result.fee_rate >= fee.fee_per_share(price)
    assert result.net_edge == pytest.approx(estimate.lower - 0.42 * (1 + 0.02) - 0.005)


def test_custom_fee_model_without_global_bound_withheld(now, market, book):
    class SpotOnly:
        def fee_per_share(self, price):
            return 0.01 * price

    _, _, provenance, estimate = approved(now, market)
    ranker = OpportunityRanker()
    assert (
        ranker.rank(market, book, estimate, [qualified(now)], provenance, now, fee_model=SpotOnly()) is None
    )
    assert "invalid_fee_model" in ranker.last_reasons
