"""Controlled future-event fixtures; never operational evidence or performance."""

from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.experimental.runtime import ExperimentalRuntime
from neraium_poly.research.phase12.admission import assess_event_proposal
from test_experimental_runtime import Feed, Fees, runtime


@pytest.fixture
def moment():
    return datetime(2026, 11, 6, 12, tzinfo=UTC)


async def test_forward_baseline_is_persisted_before_resolution_without_order_authority(tmp_path, moment):
    r, clock, _feed = runtime(tmp_path, moment)
    try:
        await r.cycle()
        s = r.state()
        e = s["event_intelligence"]
        assert e["last_error"] is None
        assert e["forecasts_pending"] == e["market_baseline_forecasts"] == 1
        assert e["independent_model_forecasts"] == e["independent_event_groups"] == 0
        assert e["scores"]["brier"] is None and e["scores"]["log_loss"] is None
        assert e["experimental_opportunities"] == e["event_order_attempts"] == 0
        assert e["rejections"]["independent_event_forecast_required"] == 1
        forecast = r.event_intelligence.ledger.forecasts()[0]
        assert forecast.timestamp == moment and forecast.evidence_cutoff == moment
        assert forecast.kind == "market_baseline" and forecast.probability == pytest.approx(0.395)
        assert forecast.probability == forecast.market_probability
        assert s["cash"] == 500 and not s["orders"] and not s["positions"]
        cp = r.event_intelligence.checkpoint()
        first_id = forecast.id
        clock.now += timedelta(seconds=1)
        await r.cycle()
        assert r.state()["event_intelligence"]["forecasts_pending"] == 1
    finally:
        await r.close()
    restarted_feed = Feed(clock)
    restarted_feed.market = _feed.market  # Preserve immutable metadata ID/content across restart.
    restarted = ExperimentalRuntime(r.config, clock=clock, feed=restarted_feed, fee_adapter=Fees())
    try:
        assert restarted.event_intelligence.ledger.forecasts()[0].id == first_id
        await restarted.cycle()
        assert restarted.state()["event_intelligence"]["forecasts_pending"] == 1
        assert restarted.event_intelligence.checkpoint()["last_by_market"] == cp["last_by_market"]
        assert restarted.state()["cash"] == 500
    finally:
        await restarted.close()


async def test_event_cycle_rejects_stale_or_degraded_frame_and_keeps_account(tmp_path, moment):
    r, _clock, feed = runtime(tmp_path, moment)
    try:
        frame = await feed.read()
        for changed in (
            frame.model_copy(update={"producer_health": {"status": "degraded"}}),
            frame.model_copy(
                update={
                    "available_at": moment - timedelta(seconds=16),
                    "timestamp": moment - timedelta(seconds=16),
                }
            ),
            frame.model_copy(
                update={
                    "timestamp": moment + timedelta(seconds=1),
                    "available_at": moment + timedelta(seconds=1),
                }
            ),
        ):
            r.event_intelligence.on_frame(changed, moment)
        assert not r.event_intelligence.ledger.forecasts()
        assert r.event_intelligence.summary()["rejections"]["fresh_healthy_event_frame_required"] == 3
        assert r.state()["cash"] == 500 and not r.state()["orders"]
    finally:
        await r.close()


async def test_trade_adapter_cannot_reinterpret_event_probability_as_horizon_mark(tmp_path, moment):
    r, _clock, feed = runtime(tmp_path, moment)
    try:
        await r.cycle()
        forecast = r.event_intelligence.ledger.forecasts()[0]
        frame = await feed.read()
        result = assess_event_proposal(forecast, frame.markets[0], frame.books[0], now=moment, enabled=True)
        assert not result["eligible"] and not result["risk_evaluated"] and not result["order_attempted"]
        assert "independent_event_forecast_required" in result["reasons"]
        assert "terminal_event_execution_capability_not_approved" in result["reasons"]
        assert r.state()["cash"] == 500 and r.state()["fills"] == 0
    finally:
        await r.close()


async def test_unavailable_event_ledger_does_not_break_paper_state_or_mask_failure(tmp_path, moment):
    r, _clock, _feed = runtime(tmp_path, moment)
    try:

        def unavailable():
            raise ValueError("controlled corrupt event chain")

        r.event_intelligence.summary = unavailable
        s = r.state()
        assert s["event_intelligence"]["research_status"] == "unavailable"
        assert s["event_intelligence"]["independent_models_enabled"] == 0
        assert s["cash"] == 500 and not s["orders"]
    finally:
        await r.close()


async def test_forecast_cutoff_is_refreshed_after_loading_outcome_evidence(tmp_path, moment):
    r, clock, _feed = runtime(tmp_path, moment)

    def slow_refresh():
        clock.now += timedelta(seconds=1)

    r.event_intelligence._refresh_outcomes = slow_refresh
    try:
        await r.cycle()
        f = r.event_intelligence.ledger.forecasts()[0]
        assert f.timestamp == f.evidence_cutoff == moment + timedelta(seconds=1)
        assert f.timestamp == clock()
    finally:
        await r.close()


async def test_rolled_back_event_journal_is_withheld_without_resetting_paper_account(tmp_path, moment):
    import sqlite3

    r, clock, feed = runtime(tmp_path, moment)
    backup = tmp_path / "controlled-empty-journal.sqlite"
    with sqlite3.connect(backup) as dest:
        r.event_intelligence.ledger.db.backup(dest)
    await r.cycle()
    assert r.state()["event_intelligence"]["forecasts_pending"] == 1
    await r.close()
    journal = r.config.data_dir / "event-intelligence" / "forecasts.sqlite"
    journal.write_bytes(backup.read_bytes())  # Controlled rollback attack fixture, never operational data.
    restarted_feed = Feed(clock)
    restarted_feed.market = feed.market
    restarted = ExperimentalRuntime(r.config, clock=clock, feed=restarted_feed, fee_adapter=Fees())
    try:
        assert restarted.event_intelligence is None
        state = restarted.state()
        assert state["event_intelligence"]["status"] == "unavailable"
        assert "rolled back" in state["event_intelligence"]["last_error"]
        assert state["cash"] == 500 and not state["orders"]
    finally:
        await restarted.close()


@pytest.mark.parametrize("verified", [False, True])
async def test_background_resolution_requires_verifier_and_never_changes_capital(
    tmp_path, moment, monkeypatch, verified
):
    from neraium_poly.research.phase12 import outcome_collector
    from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
    from neraium_poly.research.phase12.ledger import content_sha256

    r, clock, _feed = runtime(tmp_path, moment)
    await r.cycle()
    forecast = r.event_intelligence.ledger.forecasts()[0]
    clock.now = moment + timedelta(days=1, seconds=1)
    proof = {"CONTROLLED": "test-only synthetic resolution verification"}
    outcome = VerifiedEventOutcome(
        id="controlled-background-outcome",
        timestamp=clock(),
        available_at=clock(),
        source="CONTROLLED test-only",
        event_id=forecast.event_id,
        market_id=forecast.market_id,
        token_id=forecast.token_id,
        payout=1,
        resolution_rules_sha256=forecast.resolution_rules_sha256,
        settled_at=moment + timedelta(days=1),
        verification_source="CONTROLLED transport fixture",
        proof_sha256=content_sha256(proof),
        verification=proof,
    )

    async def acquire(f, market, output):
        assert f.id == forecast.id and market.available_at <= f.evidence_cutoff
        return outcome

    monkeypatch.setattr(outcome_collector, "acquire_verified_outcome", acquire)
    monkeypatch.setattr(outcome_collector, "verify_collected_outcome", lambda *args: verified)
    try:
        await r.event_intelligence.resolve_pending()
        s = r.state()
        event = s["event_intelligence"]
        assert event["forecasts_resolved"] == int(verified)
        assert event["forecasts_pending"] == int(not verified)
        assert event["resolution_collection"]["verified"] == int(verified)
        assert event["scores"]["brier"] is None  # No independently reviewed event group.
        assert s["cash"] == 500 and s["simulated_pnl"] == 0 and not s["positions"] and not s["orders"]
    finally:
        await r.close()


def test_failed_event_checkpoint_restore_releases_child_owner_without_gc(tmp_path, moment):
    import gc

    from neraium_poly.research.phase12.runtime import EventResearchRuntime

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        with pytest.raises(ValueError, match="checkpoint"):
            EventResearchRuntime(
                tmp_path / "event",
                clock=lambda: moment,
                state={"relationships": {"schema_version": "unsupported"}},
            )
        fresh = EventResearchRuntime(tmp_path / "event", clock=lambda: moment)
        assert fresh.ledger.verify()["records"] == 0
        fresh.close()
    finally:
        if was_enabled:
            gc.enable()
