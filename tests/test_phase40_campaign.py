"""Controlled engineering fixtures; none are authentic market/performance evidence."""
import hashlib
import json
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase40.campaign import ModelRouter, inventory, replay_model, run, scenario
from test_phase24_integration import NOW, adapter, inputs


@pytest.fixture(autouse=True)
def controlled_storage_capacity(monkeypatch):
    # Engineering fixtures must not require a100GiB GitHub runner disk. The
    # real campaign keeps the actual filesystem safety floor unchanged.
    from types import SimpleNamespace
    monkeypatch.setattr('neraium_poly.research.phase40.campaign.shutil.disk_usage',
        lambda _path:SimpleNamespace(free=200*1024**3,total=300*1024**3,used=100*1024**3))


def test_inventory_never_uses_market_quote_as_independent_probability():
    _m,_b,e,f,frame=inputs();rows=inventory(frame.model_dump(mode='json'),{'weather':adapter(e,f)},now=NOW)
    assert len(rows)==1 and rows[0]['bid']==.45 and rows[0]['ask']==.46
    assert rows[0]['fair_probability'] is None and rows[0]['recommended_notional']==0
    assert rows[0]['decision']=='unqualified'


def test_economic_scenario_keeps_unknown_costs_and_uncertainty_unqualified():
    m,b,_e,f,_frame=inputs();f['calibration_status']='unvalidated_research';f['id']='controlled-forecast'
    s=scenario(f,b,{'status':'verified_current_protocol_curve','rate':.02},now=NOW)
    assert s['native_payout_bounds']==[0,1] and not s['qualified']
    assert s['conservative_all_in_net_ev'] is None and s['recommended_notional']==0
    assert s['sensitivity'][0]['analysis']['actual_fill'] is False
    with pytest.raises(ValueError,match='fresh exact executable'):
        scenario(f,b.model_copy(update={'market_id':m.market_id+'other'}),{},now=NOW)
    with pytest.raises(ValueError,match='fresh exact executable'):
        scenario(f,b,{},now=NOW+timedelta(seconds=16))


def test_model_router_rejects_ambiguous_contracts_and_unregistered_models():
    _m,_b,e,f,_frame=inputs();r=ModelRouter.__new__(ModelRouter);r.models=[adapter(e,f),adapter(e,f)]
    assert r.supports({},cutoff=NOW)['reasons']==['ambiguous_exact_contract_route']
    with pytest.raises(ValueError,match='unique frozen'):r._model(f)


def test_crypto_replay_uses_the_existing_validator_tuple_contract(monkeypatch):
    from types import SimpleNamespace
    m,_b,_e,f,_frame=inputs()
    monkeypatch.setattr('neraium_poly.research.phase23.outcomes.replay_forecast',lambda *a,**kw:(m,SimpleNamespace(rules_sha256=f['rules_sha256']),None))
    replay_model({},f,{},now=NOW)
    with pytest.raises(ValueError,match='crypto source replay identity mismatch'):
        replay_model({},{**f,'token_id':'unrelated'}, {},now=NOW)


async def test_bounded_campaign_reuses_real_engines_and_recovers_pending_outcomes(tmp_path,monkeypatch):
    _m,_b,e,f,frame=inputs();mod=adapter(e,f)
    mod.replay=lambda forecast,evidence,as_of:{'verified':True}  # CONTROLLED fixture verifier only.
    async def fee_unavailable(*_a,**_kw):return None
    monkeypatch.setattr('neraium_poly.experimental.fees.AuditedFeeAdapter.observed_fee',fee_unavailable)
    async def fetch():return frame.model_dump(mode='json')
    output=tmp_path/'isolated-campaign'
    report=await run(output,seconds=30,clock=lambda:NOW,fetch=fetch,models={'weather':mod})
    assert report['markets_evaluated']==report['prospective_forecasts']==1
    assert report['independent_source_replayed_forecasts']==1
    assert report['qualified_opportunities']==report['shadow']['hypothetical_fills']==0
    assert report['shadow']['positions']==0 and report['shadow']['realized_simulated_pnl'] is None
    assert report['outcome_verification']['pending_forecasts']==1
    assert report['universe_decisions'][0]['forecast_ids']
    assert report['depth_scenarios'][0]['conservative_all_in_net_ev'] is None
    store=EventStore(output/'campaign.sqlite');previous=None;checksum=None
    for payload,digest in store.connection.execute("SELECT payload,digest FROM events WHERE kind='CampaignEvidence' ORDER BY rowid"):
        record=json.loads(payload);assert hashlib.sha256(payload.encode()).hexdigest()==digest
        assert (record['previous_record_id'],record['previous_record_sha256'])==(previous,checksum)
        previous,checksum=record['id'],digest
    store.close()
    resumed=await run(output,seconds=30,clock=lambda:NOW,models={'weather':mod},resume=True,settle_only=True)
    assert resumed['outcomes']['pending_forecasts']==1 and resumed['outcomes']['verified_forecasts']==0
    assert resumed['forecast_performance']['domains']['counts']['individually_verified_forecasts']==0
    assert resumed['shadow']['orders_attempted']==0


async def test_stale_or_duplicate_feed_is_not_an_opportunity(tmp_path):
    _m,_b,e,f,frame=inputs()
    async def stale():return frame.model_dump(mode='json')
    with pytest.raises(ValueError,match='fresh market frame'):
        await run(tmp_path/'stale',seconds=30,clock=lambda:NOW+timedelta(seconds=16),fetch=stale,models={'weather':adapter(e,f)})


async def test_real_execution_environment_cannot_start_campaign(tmp_path,monkeypatch):
    monkeypatch.setenv('LIVE_TRADING_ENABLED','true')
    with pytest.raises(ValueError,match='paper-only'):
        await run(tmp_path/'never-created',seconds=30)
    assert not (tmp_path/'never-created').exists()
