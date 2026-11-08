"""Synthetic wiring checks; genuine event observations are separately archived."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase32.pairs import PairResearch, scan_pairs
from test_phase24_integration import NOW, inputs


def test_pair_publication_restart_cannot_create_orders_or_account_access(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');frame=inputs()[-1]
    volume=SimpleNamespace(id='CONTROLLED-economic-study',timestamp=NOW,decision_frame_sha256=digest(frame.model_dump(mode='json')),model_dump=lambda **k:{'id':'CONTROLLED-economic-study'})
    try:
        p=PairResearch(store,clock=lambda:NOW,can_write=lambda:True);p.observe(volume,frame)
        assert p.status()['status']=='conditional_research_only'
        assert store.count(kind='PairStudy')==1
        recovered=PairResearch(store,clock=lambda:NOW+timedelta(seconds=1),can_write=lambda:True);recovered.observe(volume,frame)
        assert store.count(kind='PairStudy')==1 and not recovered.status()['trading_authority']
        assert not recovered.status()['qualified_opportunities']
    finally:store.close()


def test_pair_publication_backpressure_withholds_previous_findings(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');allow=[True];frame=inputs()[-1]
    volume=SimpleNamespace(id='CONTROLLED',timestamp=NOW,decision_frame_sha256=digest(frame.model_dump(mode='json')),model_dump=lambda **k:{})
    try:
        p=PairResearch(store,clock=lambda:NOW,can_write=lambda:allow[0]);p.observe(volume,frame);allow[0]=False;p.observe(volume,frame)
        assert p.status()['status']=='withheld' and 'findings' not in p.status()
    finally:store.close()


def test_pair_snapshot_never_overwrites_incompatible_market_rules():
    frame=inputs()[-1];r=scan_pairs(frame,as_of=NOW)
    assert r['positive_conditional_gross_pairs']==0 and r['qualified_opportunities']==0
    assert r['realized_pnl'] is None and not r['trading_authority']


async def test_weather_macro_routing_does_not_change_crypto_license_gate(monkeypatch,tmp_path):
    from neraium_poly.research.phase32 import macro, scoring, weather
    async def official(f,**kwargs):return {'event_result_verified':False,'reason':f['domain']+'_CONTROLLED'}
    monkeypatch.setattr(weather,'verify_weather_event',official);monkeypatch.setattr(macro,'verify_macro_event',official)
    for domain in ['weather','economics']:
        r=await scoring.verify_event({'domain':domain},directory=tmp_path,clock=lambda:NOW)
        assert r['reason']==domain+'_CONTROLLED'
    with pytest.raises((TypeError,ValueError,KeyError)):
        await scoring.verify_event({'domain':'crypto'},directory=tmp_path,clock=lambda:NOW)


@pytest.mark.parametrize("fault",["frame","future"])
def test_pair_record_is_bound_to_exact_economic_frame_and_causal_clock(tmp_path,fault):
    store=EventStore(tmp_path/'controlled.sqlite');frame=inputs()[-1]
    volume=SimpleNamespace(id="CONTROLLED",timestamp=NOW+timedelta(seconds=1) if fault=="future" else NOW,
        decision_frame_sha256="WRONG" if fault=="frame" else digest(frame.model_dump(mode="json")),model_dump=lambda **k:{})
    try:
        p=PairResearch(store,clock=lambda:NOW,can_write=lambda:True);p.observe(volume,frame)
        assert p.status()['status']=="withheld" and store.count(kind="PairStudy")==0
    finally:store.close()


@pytest.mark.parametrize("attempted",[True,False])
async def test_only_unattempted_matured_backlog_gets_fast_catchup(monkeypatch,attempted):
    from neraium_poly.research.phase30.scoring import OfficialEventScoring
    from neraium_poly.research.phase32.scoring import DomainEventScoring
    obj=DomainEventScoring.__new__(DomainEventScoring)
    f={"id":"CONTROLLED-F","domain":"weather","event_end_time":(NOW-timedelta(hours=1)).isoformat()}
    entries=[{"type":"forecast","replay_verified":True,"forecast":f,"forecast_sha256":"SHA","source_study_sha256":"SOURCE"}]
    obj.clock=lambda:NOW;obj.index=SimpleNamespace(snapshot=lambda:(entries,{}));obj.store=SimpleNamespace(get=lambda _:None)
    obj.enrollment_id="CONTROLLED";obj.attempts={f['id']:NOW} if attempted else {}
    async def base(self):self.next_check=NOW+timedelta(seconds=300);return True
    monkeypatch.setattr(OfficialEventScoring,"step",base)
    assert await obj.step()
    assert obj.next_check==NOW+timedelta(seconds=300 if attempted else 10)
