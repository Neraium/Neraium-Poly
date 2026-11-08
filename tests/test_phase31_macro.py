"""Controlled macro qualification fixtures, not actual forecasts/outcomes."""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase31.macro import (
    CPI_API,
    CPI_POLICY,
    collect_cpi_availability,
    cpi_qualification,
    macro_readiness,
)

NOW=datetime(2026,11,8,19,30,tzinfo=UTC)
POLICY='BLS will not publish 12-month percent changes for October 2026 for indexes where October 2025 data are not available.'


def bundle():
    raw={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'CUUR0000SA0','data':[
        {'year':'2025','period':'M10','value':'-','footnotes':[{'code':'X','text':'Data unavailable due to the 2025 lapse in appropriations'}]},
        {'year':'2025','period':'M11','value':'324.122','footnotes':[]}]}]}}
    ev=[]
    for url,body in [(CPI_API,json.dumps(raw)),(CPI_POLICY,'<html><p>'+POLICY+'</p></html>')]:
        ev.append({'source_url':url,'requested_at':NOW.isoformat(),'retrieved_at':NOW.isoformat(),'available_at':NOW.isoformat(),
            'source_timestamp':None,'raw_utf8':body,'content_sha256':hashlib.sha256(body.encode()).hexdigest()})
    return {'evidence':ev,'evidence_sha256':digest(ev),'available_at':NOW.isoformat()}


def test_official_missing_october_denominator_requires_fallback_review_not_imputation():
    b=bundle();r=cpi_qualification(b,target_year=2026,target_month=10,as_of=NOW)
    assert r['status']=='structural_source_blocker' and r['source_structural_missingness']
    assert not r['denominator_available'] and r['denominator_value'] is None
    assert not r['target_annual_change_publication_supported']
    assert r['forecast_probability'] is None and r['outcome'] is None
    assert not r['fallback_outcome_verified'] and not r['trading_authority']
    assert 'contract_fallback_interpretation_requires_review' in r['reasons']


def test_policy_does_not_generalize_to_other_month_or_create_probability():
    r=cpi_qualification(bundle(),target_year=2026,target_month=11,as_of=NOW)
    assert r['denominator_available'] and r['denominator_value']=='324.122'
    assert not r['source_structural_missingness'] and r['forecast_probability'] is None
    assert not r['numerical_probability_supported']


@pytest.mark.parametrize('fault',['hash','url','future','duplicate','foreign_series','policy_absent','footnote_absent'])
def test_cpi_proof_requirements_never_silently_assert_structural_absence(fault):
    b=bundle()
    if fault=='hash':b['evidence'][0]['content_sha256']='0'*64
    elif fault=='url':b['evidence'][0]['source_url']='https://unreviewed.example/'
    elif fault=='future':b['evidence'][0]['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    else:
        if fault=='policy_absent':b['evidence'][1]['raw_utf8']='<html>ordinary release</html>'
        else:
            raw=json.loads(b['evidence'][0]['raw_utf8'])
            if fault=='duplicate':raw['Results']['series'][0]['data'].append(deepcopy(raw['Results']['series'][0]['data'][0]))
            elif fault=='foreign_series':raw['Results']['series'][0]['seriesID']='FOREIGN'
            else:raw['Results']['series'][0]['data'][0]['footnotes']=[]
            b['evidence'][0]['raw_utf8']=json.dumps(raw)
        for e in b['evidence']:e['content_sha256']=hashlib.sha256(e['raw_utf8'].encode()).hexdigest()
    b['evidence_sha256']=digest(b['evidence'])
    if fault in ('policy_absent','footnote_absent'):
        r=cpi_qualification(b,target_year=2026,target_month=10,as_of=NOW)
        assert r['source_structural_missingness']==(fault=='policy_absent')
        assert r['target_annual_change_publication_supported'] is None
    else:
        with pytest.raises((ValueError,KeyError)):cpi_qualification(b,target_year=2026,target_month=10,as_of=NOW)


def entry(fid='f',*,family='fomc',when=NOW+timedelta(days=30)):
    refs={'fomc':'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm','spx':'https://www.wsj.com/market-data/stocks'}
    f={'id':fid,'domain':'economics' if family=='fomc' else 'finance','model_id':family+'-controlled-v1','event_end_time':when.isoformat(),
       'timestamp':(NOW-timedelta(days=1)).isoformat(),'market_id':'market','event_id':'event','token_id':'token'}
    return {'type':'forecast','replay_verified':True,'forecast':f,'forecast_sha256':digest(f),'available_at':(NOW-timedelta(hours=23)).isoformat(),
        'review':{'canonical_group_id':'controlled-parent','descriptor':{'resolution_reference':refs[family]}}}


def test_future_event_is_not_a_missing_outcome_and_models_do_not_inflate_group_n():
    a=entry();b=entry('f2');r=macro_readiness([a,b,a],as_of=NOW)
    assert r['forecasts']==2 and r['canonical_event_groups']==1
    assert r['counts']=={'NOT_YET_MATURE':2} and r['official_outcomes_verified']==0
    assert r['effective_independent_sample_size'] is None
    assert all(x['forecast_probability'] is None for x in r['rows'])


def test_matured_or_conflicting_reference_never_becomes_a_label():
    a=entry(when=NOW-timedelta(hours=1));b=entry('other',family='spx');b['review']['descriptor']['resolution_reference']='https://fred.stlouisfed.org/'
    r=macro_readiness([a,b],as_of=NOW)
    assert r['counts']=={'OFFICIAL_RESULT_REVIEW_REQUIRED':1,'REFERENCE_IDENTITY_MISMATCH':1}
    assert all(x['native_payout_verified'] is False for x in r['rows'])
    conflict=deepcopy(a);conflict['forecast_sha256']='f'*64
    r=macro_readiness([a,conflict],as_of=NOW)
    assert r['forecasts']==0 and r['counts']['CONFLICTING_ORIGINAL_FORECAST_IDENTITY']==1


async def test_acquisition_records_exact_hashes_and_rejects_oversize_body():
    b=bundle();mapping={e['source_url']:e['raw_utf8'] for e in b['evidence']}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=mapping[str(r.url)]))) as client:
        r=await collect_cpi_availability(clock=lambda:NOW,client=client)
        assert r['evidence_sha256']==digest(r['evidence'])
        assert all(e['source_timestamp'] is None for e in r['evidence'])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'x'*(2*1024**2+1)))) as client:
        with pytest.raises(ValueError,match='byte_budget'):await collect_cpi_availability(clock=lambda:NOW,client=client)


async def test_policy_access_denied_preserves_structured_missingness_without_bypass():
    b=bundle();api=b['evidence'][0]['raw_utf8'];calls=[]
    def respond(request):
        calls.append(str(request.url));return httpx.Response(200,text=api) if str(request.url)==CPI_API else httpx.Response(403,text='denied')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        observed=await collect_cpi_availability(clock=lambda:NOW,client=client)
    assert calls==[CPI_API,CPI_POLICY] and len(observed['evidence'])==1
    r=cpi_qualification(observed,target_year=2026,target_month=10,as_of=NOW)
    assert r['source_structural_missingness'] and not r['publication_policy_source_verified']
    assert r['target_annual_change_publication_supported'] is None
    assert r['forecast_probability'] is None and not r['fallback_outcome_verified']
    assert observed['source_errors'][0]['status_code']==403


def test_exact_contract_qualification_never_applies_CPI_policy_to_another_event():
    from neraium_poly.research.phase31.macro import qualify_cpi_market
    from test_phase24_weather_economics import market
    m=market('cpi');r=qualify_cpi_market(m,bundle(),as_of=NOW)
    assert r['market_id']==m.market_id and r['rules_sha256']
    assert r['statistical_model_estimation_blocked'] and r['contract_fallback_review_required']
    assert r['forecast_probability'] is None and not r['native_payout_verified']
    wrong=m.model_copy(update={'resolution_rules':m.resolution_rules+' ambiguous'})
    assert qualify_cpi_market(wrong,bundle(),as_of=NOW)['status']=='unsupported_contract'
