"""Controlled fixtures; never report these observations as live outcomes."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase28.findings import build_economic_findings, combine_economic_reports
from neraium_poly.research.phase29.costs import level_fees, replay_fee
from test_phase27_findings import NOW, inputs


class Store:
    def __init__(self, records):self.records=records
    def get(self, identity):return self.records.get(identity)


def observations(token):
    stamp=NOW.isoformat();source='https://clob.polymarket.com'
    ps=[{'condition_id':'condition','primary_token_id':token,'secondary_token_id':'opposite'},
        {'c':'condition','t':[{'t':token}],'fd':{'r':.04,'e':1,'to':True}}]
    paths=['/markets-by-token/'+token,'/clob-markets/condition'];records={}
    for n,p in enumerate(ps):records[str(n)]={'id':str(n),'timestamp':stamp,'available_at':stamp,'source':source,'url':source+paths[n],'content_sha256':digest(p),'payload':p}
    records['observation']={'id':'observation','timestamp':stamp,'available_at':stamp,'source':source,'token_id':token,'fee_rate':.04,'raw_response_ids':['0','1']}
    return Store(records),{'evidence_id':'observation'}


def test_fee_exact_official_curve_and_identity_without_certifying_all_costs():
    _,f,frame=inputs();store,obs=observations(f['token_id'])
    proof=replay_fee(obs,store,token_id=f['token_id'],as_of=NOW)
    assert proof['status']=='verified_current_protocol_curve' and proof['rate']==.04
    assert not proof['all_in_costs_verified'] and proof['source_timestamp'] is None
    fee=level_fees(frame.books[0],proof)
    assert fee['levels'][0]['formula_fee_per_share']==pytest.approx(.04*.41*.59)
    assert not fee['rounding_fragmentation_verified']


@pytest.mark.parametrize('fault',['other_token','hash','future','stale','coefficient','legacy_bps','missing_record'])
def test_fee_originals_identity_and_availability_fail_closed(fault):
    _,f,_=inputs();store,obs=observations(f['token_id'])
    if fault=='other_token':store.records['observation']['token_id']='different'
    elif fault=='hash':store.records['1']['content_sha256']='f'*64
    elif fault=='future':store.records['1']['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='stale':store.records['observation']['available_at']=(NOW-timedelta(seconds=301)).isoformat();store.records['observation']['timestamp']=store.records['observation']['available_at']
    elif fault=='coefficient':store.records['observation']['fee_rate']=.08
    elif fault=='legacy_bps':
        store.records['1']['payload']={'c':'condition','t':[{'t':f['token_id']}],'base_fee':1000};store.records['1']['content_sha256']=digest(store.records['1']['payload'])
    else:store.records.pop('0')
    result=replay_fee(obs,store,token_id=f['token_id'],as_of=NOW)
    assert result['status']=='unavailable' and not result['all_in_costs_verified']


def test_stale_forecast_allows_explicit_diagnostic_not_current_economics_or_shadow():
    s,f,frame=inputs();old=deepcopy(s);later=NOW+timedelta(seconds=301)
    b=frame.books[0].model_copy(update={'timestamp':later,'available_at':later})
    current=frame.model_copy(update={'timestamp':later,'available_at':later,'books':(b,)})
    result=build_economic_findings([s],current,as_of=later,verified_forecast_ids=[f['id']]);r=result['findings'][0]
    p=r['pipeline'];assert p['economic_evaluation_completed'] and not p['forecast_fresh_for_admission']
    assert p['hypothesis_sensitivity']['scope']=='original_forecast_current_book_counterfactual'
    assert p['hypothesis_sensitivity']['original_forecast_timestamp']==f['timestamp']
    assert p['hypothesis_sensitivity']['net_expected_profit'] is None
    assert r['execution_analysis'] is None and not r['shadow_eligible'] and not r['qualified_research']
    assert r['scenario_expected_net_profit'] is None and result['rankings']==[] and result['scenario_rankings']==[]
    assert s==old
    merged=combine_economic_reports([result,result],as_of=later)
    assert merged['pipeline_counts']['economic_evaluation_completed']==1


@pytest.mark.parametrize('fault',['missing','stale','wrong_token','changed_rules'])
def test_diagnostic_valuation_never_uses_unqualified_books(fault):
    s,f,frame=inputs();raw=frame.model_dump(mode='json')
    if fault=='missing':raw['books']=[]
    elif fault=='stale':raw['books'][0]['timestamp']=(NOW-timedelta(seconds=16)).isoformat()
    elif fault=='wrong_token':raw['books'][0]['token_id']='different'
    else:raw['markets'][0]['resolution_rules']+=' changed'
    r=build_economic_findings([s],raw,as_of=NOW,verified_forecast_ids=[f['id']])['findings'][0]
    assert not r['pipeline']['economic_evaluation_completed'] and r['pipeline']['hypothesis_sensitivity'] is None


def test_fresh_retrieval_receipts_replay_deduplicated_old_fee_content():
    _,f,_=inputs();store,obs=observations(f['token_id']);old=(NOW-timedelta(hours=1)).isoformat()
    for key in ['0','1']:
        raw=store.records[key];raw['timestamp']=old;raw['available_at']=old
        store.records['receipt'+key]={'id':'receipt'+key,'timestamp':NOW.isoformat(),'available_at':NOW.isoformat(),
            'source':raw['source'],'raw_response_id':key,'content_sha256':raw['content_sha256'],'url':raw['url']}
    store.records['observation']['retrieval_ids']=['receipt0','receipt1']
    proof=replay_fee(obs,store,token_id=f['token_id'],as_of=NOW)
    assert proof['status']=='verified_current_protocol_curve'
    store.records['receipt1']['raw_response_id']='0'
    assert replay_fee(obs,store,token_id=f['token_id'],as_of=NOW)['status']=='unavailable'


async def test_real_adapter_records_new_receipts_for_duplicate_response_content(tmp_path):
    import httpx
    from neraium_poly.data.store import EventStore
    from neraium_poly.experimental.fees import AuditedFeeAdapter
    token='controlled-a';parent={'condition_id':'condition','primary_token_id':token,'secondary_token_id':'other'}
    details={'c':'condition','t':[{'t':token}],'fd':{'r':.04,'e':1,'to':True}}
    store=EventStore(tmp_path/'fees.sqlite')
    adapter=AuditedFeeAdapter(store,lambda:True,client=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r:httpx.Response(200,json=parent if 'markets-by-token' in r.url.path else details))))
    try:
        one=await adapter.observed_fee(token);two=await adapter.observed_fee(token)
        assert one['raw_response_ids']==two['raw_response_ids']
        assert one['retrieval_ids']!=two['retrieval_ids']
        assert len(store.replay(kind='PublicFeeResponse'))==2
        assert len(store.replay(kind='PublicFeeReceipt'))==4
    finally:await adapter.close();store.close()


def test_bounded_projection_selection_does_not_rewrite_original_study_hash():
    s,f,frame=inputs();other=deepcopy(f);other['id']='CONTROLLED-other-original';s['forecasts'].append(other)
    original=digest(s)
    r=build_economic_findings([s],frame,as_of=NOW,verified_forecast_ids=[f['id']],included_forecast_ids=[f['id']])
    assert len(r['findings'])==1 and r['findings'][0]['original_study_sha256']==original
    assert 'independent_original_source_model_replay_required' not in r['findings'][0]['reasons']
    assert len(s['forecasts'])==2 and digest(s)==original
