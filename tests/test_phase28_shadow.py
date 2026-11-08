"""Controlled shadow fixtures. No fixture is authentic price/performance evidence."""
import copy
import hashlib
from datetime import timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase28.shadow import ShadowResearch
from test_phase24_integration import NOW


class Clock:
    def __init__(self):self.now=NOW
    def __call__(self):return self.now


def frame(clock, *, size=100, asks=None, bid_size=None, token='CONTROLLED-token', event='CONTROLLED-parent'):
    b=OrderBookSnapshot(id='CONTROLLED-book-'+token+clock.now.isoformat(),timestamp=clock.now,available_at=clock.now,
        source='https://clob.polymarket.com',market_id='CONTROLLED-market-'+token,token_id=token,
        bids=(PriceLevel(price=.5,size=bid_size or size),),
        asks=tuple(PriceLevel(price=p,size=q) for p,q in (asks or [(.51,size)])))
    m=MarketSnapshot(id='CONTROLLED-metadata-'+token,timestamp=NOW,available_at=NOW,
        source='https://gamma-api.polymarket.com',market_id=b.market_id,token_id=token,event_id=event,
        question='CONTROLLED?',resolution_rules='CONTROLLED-rule',end_time=NOW+timedelta(days=1),status='active',probability=.5,min_order_size=5,tick_size=.0001)
    return {'id':'CONTROLLED-frame-'+clock.now.isoformat(),'books':[b.model_dump(mode='json')],'markets':[m.model_dump(mode='json')]}


def finding(raw,clock,*,fid='CONTROLLED-forecast',strategies=None,qualified=True):
    m=raw['markets'][0];b=raw['books'][0]
    return {'id':'CONTROLLED-finding-'+fid+clock.now.isoformat(),'forecast_id':fid,'market_id':m['market_id'],
        'event_id':m['event_id'],'token_id':m['token_id'],'decision_at':clock.now.isoformat(),
        'book_sha256':digest(b),'frame_sha256':digest(raw),'shadow_eligible':qualified,'qualified_research':qualified,
        'research_only':True,'trading_authority':False,'conservative_expected_net_profit':.01,
        'correlation':{'canonical_group_id':m['event_id'],'dependency_tags':['CONTROLLED-common-driver']},
        'strategy_eligibility':strategies or ['small_edge']}


def verify(row,raw,*,as_of):
    return {'verified':True,'finding_id':row['id'],**{k:row[k] for k in ['forecast_id','market_id','token_id','event_id']},
        'book_sha256':digest(raw['books'][0]),'calibration_verified':True,'native_costs_verified':True,'settlement_rules_verified':True,
        'forecast_at':NOW.isoformat(),'evidence_available_at':NOW.isoformat(),'event_end_time':(NOW+timedelta(days=1)).isoformat(),
        'lower_payout':.511,'expected_payout':.512,'upper_payout':.513,'fee_rate':0.,'slippage_per_share':0.,'settlement_cost_per_share':0.,
        'exit_fee_rate':0.,'min_order_size':5.,'resolution_rules_sha256':hashlib.sha256(b'CONTROLLED-rule').hexdigest(),
        'independent_source_groups':2,'forecast_uncertainty':.05}


def report(*rows):return {'findings':list(rows),'research_only':True,'trading_authority':False}


def open_position(tmp_path, *, size=100, bid_size=None, verifier=verify):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();engine=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verifier)
    initial=frame(clock);row=finding(initial,clock);engine.step(report(row),initial)
    clock.now+=timedelta(seconds=.5);engine.step(report(),frame(clock,size=size,bid_size=bid_size))
    return store,clock,engine


def final_proof(position,*,at_time=NOW+timedelta(hours=1),**changes):
    return {'verified':True,**{k:position[k] for k in ['market_id','token_id','event_id','forecast_id','resolution_rules_sha256']},
        'final':True,'disputed':False,'resolved_at':at_time.isoformat(),'available_at':(at_time+timedelta(seconds=1)).isoformat(),
        'payout_per_share':1.,'source_sha256':'a'*64,**changes}


def test_unvalidated_scenarios_and_missing_proofs_never_create_orders(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True)
    try:
        f=frame(clock);e.step(report(finding(f,clock,qualified=False)),f)
        clock.now+=timedelta(seconds=1);f=frame(clock);e.step(report(finding(f,clock)),f)
        s=e.status();assert s['orders_attempted']==s['positions']==0 and s['realized_simulated_pnl'] is None
        assert s['actual_account_access'] is False and 'independent_candidate_proof_replay_unavailable' in s['rejections']
    finally:store.close()


def test_small_edge_below_three_cents_reserves_then_fills_only_after_latency(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);e.step(report(finding(f,clock)),f)
        assert e.status()['capital_reserved']==5 and e.status()['positions']==0
        clock.now+=timedelta(seconds=.1);e.step(report(),frame(clock));assert e.status()['positions']==0
        clock.now+=timedelta(seconds=.3);e.step(report(),frame(clock));s=e.status()
        assert s['hypothetical_fills']==s['positions']==1 and s['hypothetical_cash']==pytest.approx(495)
        assert s['realized_simulated_pnl'] is None and s['unrealized_simulated_pnl']<0
        assert s['trading_authority'] is False
    finally:store.close()


def test_partial_fills_expire_remainder_without_inventing_position_quantity(tmp_path):
    store,clock,e=open_position(tmp_path,size=40)
    try:
        assert e.status()['position_quantity']==pytest.approx(4)
        assert e.status()['pending_orders']==1
        clock.now=NOW+timedelta(seconds=61);e.step(report(),frame(clock,size=40))
        assert e.status()['expired']==1 and e.status()['capital_reserved']==0
        assert e.status()['position_quantity']==pytest.approx(4)
    finally:store.close()


def test_consumed_asks_shared_across_strategies_and_not_replenished_by_new_snapshot(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);e.step(report(finding(f,clock,strategies=['small_edge','high_conviction'])),f)
        assert e.status()['capital_reserved']==15
        clock.now+=timedelta(seconds=1);e.step(report(),frame(clock));quantity=e.status()['position_quantity'];assert quantity==pytest.approx(10)
        clock.now+=timedelta(seconds=1);e.step(report(),frame(clock));assert e.status()['position_quantity']==pytest.approx(quantity)
        assert sum(e.state['depth_used'].values())==pytest.approx(10)
    finally:store.close()


def test_multi_level_fill_uses_actual_level_prices(tmp_path):
    # Two positive but tiny marginal edges.
    store=EventStore(tmp_path/'CONTROLLED-levels.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);e.step(report(finding(f,clock)),f);clock.now+=timedelta(seconds=.5)
        e.step(report(),frame(clock,asks=[(.51,20),(.5105,100)]))
        p=next(iter(e.state['positions'].values()));assert p['quantity']<5/.51
        assert p['cost']==pytest.approx(5) and len(e.state['depth_used'])==2
    finally:store.close()


def test_common_dependency_limit_blocks_concentrated_reservations(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        for i in range(15):
            clock.now=NOW+timedelta(milliseconds=i)
            f=frame(clock,token=f'CONTROLLED-{i}',event=f'CONTROLLED-event-{i}');row=finding(f,clock,fid=f'CONTROLLED-f-{i}')
            e.step(report(row),f)
        assert e.status()['capital_reserved']==pytest.approx(50)
        assert e.status()['orders_attempted']==10 and e.status()['positions']==0
        assert e.status()['exposure']<=100
    finally:store.close()


def test_stale_native_timestamp_cannot_fill_despite_fresh_receipt(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);e.step(report(finding(f,clock)),f)
        clock.now+=timedelta(seconds=20);old=frame(clock);old['books'][0]['timestamp']=NOW.isoformat()
        e.step(report(),old);assert e.status()['positions']==0 and e.status()['capital_reserved']==5
    finally:store.close()


def test_acknowledgement_loss_and_restart_do_not_duplicate_reservations(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify);append=store.append
    try:
        def failed(record):append(record);raise OSError('CONTROLLED lost acknowledgement')
        monkeypatch.setattr(store,'append',failed);f=frame(clock);r=report(finding(f,clock))
        with pytest.raises(OSError):e.step(r,f)
        monkeypatch.setattr(store,'append',append);assert not e.step(r,f)
        restored=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
        assert not restored.step(r,f) and restored.status()['capital_reserved']==5
        assert store.count(kind='ShadowStudy')==1
    finally:store.close()


def test_cancellation_releases_reservation_idempotently(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);e.step(report(finding(f,clock)),f);oid=next(iter(e.state['orders']))
        assert e.cancel(oid) and not e.cancel(oid)
        assert e.status()['capital_reserved']==0 and e.status()['positions']==0 and e.status()['hypothetical_cash']==500
    finally:store.close()


def test_unresolved_or_unproved_outcome_never_creates_realized_profit(tmp_path):
    store,clock,e=open_position(tmp_path)
    try:
        oid=next(iter(e.state['positions']))
        with pytest.raises(TypeError):e.settle({'position_id':oid})
        assert e.status()['realized_simulated_pnl'] is None
        e.outcome_verifier=lambda *a,**k:final_proof(e.state['positions'][oid],final=False)
        clock.now=NOW+timedelta(hours=2)
        with pytest.raises(ValueError,match='final_undisputed'):e.settle({'position_id':oid})
        assert e.status()['realized_simulated_pnl'] is None
    finally:store.close()


@pytest.mark.parametrize('changes,reason', [({'token_id':'WRONG'},'identity'),({'available_at':(NOW+timedelta(days=5)).isoformat()},'time_order'),({'disputed':True},'undisputed')])
def test_settlement_identity_finality_and_availability_are_required(tmp_path,changes,reason):
    store,clock,e=open_position(tmp_path)
    try:
        oid=next(iter(e.state['positions']));p=e.state['positions'][oid]
        e.outcome_verifier=lambda *a,**k:final_proof(p,**changes);clock.now=NOW+timedelta(hours=2)
        with pytest.raises(ValueError,match=reason):e.settle({'position_id':oid})
        assert e.status()['settlements']==0
    finally:store.close()


def test_verified_settlement_scores_only_filled_quantity_and_preserves_account_sentinel(tmp_path):
    sentinel=tmp_path/'unrelated-certified-account.sqlite';sentinel.write_bytes(b'CONTROLLED sentinel original');sha=hashlib.sha256(sentinel.read_bytes()).hexdigest()
    store,clock,e=open_position(tmp_path,size=40)
    try:
        oid=next(iter(e.state['positions']));p=copy.deepcopy(e.state['positions'][oid]);e.outcome_verifier=lambda *a,**k:final_proof(p)
        clock.now=NOW+timedelta(hours=2);assert e.settle({'position_id':oid}) and not e.settle({'position_id':oid})
        assert e.status()['realized_simulated_pnl']==pytest.approx(4-4*.51)
        assert e.status()['positions']==0 and e.status()['capital_reserved']==0
        assert hashlib.sha256(sentinel.read_bytes()).hexdigest()==sha
        assert e.status()['verified_settled_parent_events']==1
    finally:store.close()


def test_incomplete_bid_depth_cannot_be_presented_as_complete_unrealized_pnl(tmp_path):
    store,_clock,e=open_position(tmp_path,size=40,bid_size=1)
    try:
        assert e.status()['positions']==1 and e.status()['unrealized_simulated_pnl'] is None
        assert e.status()['mark_status']=='incomplete_exit_liquidity' and e.status()['drawdown'] is None
    finally:store.close()


def test_future_evidence_and_tampered_checkpoint_fail_closed(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock()
    def future(*a,**kw):return {**verify(*a,**kw),'evidence_available_at':(NOW+timedelta(seconds=1)).isoformat()}
    e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=future)
    try:
        f=frame(clock);e.step(report(finding(f,clock)),f);assert e.status()['orders_attempted']==0
        assert 'candidate_evidence_availability_invalid' in e.status()['rejections']
        bad=copy.deepcopy(e.last_record);bad['checkpoint_sha256']='CONTROLLED-corrupt'
        with pytest.raises(ValueError,match='checksum'):e._adopt(bad)
        assert unpack_checkpoint(e.last_record['checkpoint'])['orders']=={}
    finally:store.close()


def test_current_native_lot_and_tick_constraints_cannot_be_bypassed(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);f['markets'][0]['min_order_size']=50
        e.step(report(finding(f,clock)),f)
        assert e.status()['orders_attempted']==0
        assert 'exact_current_native_minimum_order_size_required' in e.status()['rejections']
        clock.now+=timedelta(seconds=1);f=frame(clock,asks=[(.5105,100)]);f['markets'][0]['tick_size']=.01
        e.step(report(finding(f,clock)),f)
        assert e.status()['orders_attempted']==0 and 'current_book_price_tick_mismatch' in e.status()['rejections']
    finally:store.close()


def test_post_latency_native_constraint_change_withholds_existing_order_fill(tmp_path):
    store=EventStore(tmp_path/'CONTROLLED.sqlite');clock=Clock();e=ShadowResearch(store,clock=clock,can_write=lambda:True,candidate_verifier=verify)
    try:
        f=frame(clock);e.step(report(finding(f,clock)),f)
        clock.now+=timedelta(seconds=1);f=frame(clock);f['markets'][0]['min_order_size']=50
        e.step(report(),f)
        assert e.status()['positions']==0 and e.status()['capital_reserved']==5
        assert all(v['realized_pnl'] is None for v in e.status()['strategies'].values())
    finally:store.close()
