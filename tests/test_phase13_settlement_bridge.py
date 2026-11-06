"""Controlled genuine-adapter boundary tests; no authentic settlements claimed."""
import asyncio
from datetime import timedelta

import pytest
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from neraium_poly.research.phase13.runtime import SportsSettlementReference
from test_phase9_qualification import NOW
from test_phase12_outcome_collector import controlled_clients, no_sync_wait  # noqa: F401


async def test_external_original_reference_passes_real_native_chain_acquisition_and_replay(tmp_path):
    f, m, public, rpc = controlled_clients()
    reference = SportsSettlementReference(
        id=f.id, event_id=f.event_id, market_id=f.market_id, token_id=f.token_id,
        timestamp=f.timestamp, evidence_cutoff=f.evidence_cutoff,
        resolution_rules_sha256=f.resolution_rules_sha256, original_record_sha256="a" * 64,
    )
    try:
        outcome = await acquire_verified_outcome(reference, m, tmp_path / "proof", client=public,
                                                  rpc_client=rpc, clock=lambda: NOW)
        assert outcome is not None
        assert await asyncio.to_thread(verify_collected_outcome, outcome, m, reference, tmp_path)
        changed = reference.model_copy(update={"original_record_sha256": "b" * 64})
        assert not await asyncio.to_thread(verify_collected_outcome, outcome, m, changed, tmp_path)
        assert not isinstance(reference, type(f))  # Never fabricate a binary EventForecast.
    finally:
        await public.aclose()
        rpc.close()


def test_reference_revalidation_blocks_model_copy_time_bypass():
    from neraium_poly.research.phase12.outcome_collector import _forecast_reference
    reference = SportsSettlementReference(id="f", event_id="e", market_id="m", token_id="t",
        timestamp=NOW, evidence_cutoff=NOW, resolution_rules_sha256="a" * 64,
        original_record_sha256="b" * 64)
    with pytest.raises(ValueError):
        _forecast_reference(reference.model_copy(update={"evidence_cutoff": NOW + timedelta(seconds=1)}))
