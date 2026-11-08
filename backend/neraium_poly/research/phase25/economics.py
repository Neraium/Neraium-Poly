"""ONS UK first-release GDP research; current vintages are not old release labels."""
import hashlib
import html
import json
import math
import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import NormalDist, mean, stdev

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import finance

URL='https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/ihyq/pn2/data'
SOURCE='https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/gdpfirstquarterlyestimateuk/previousreleases'
PROVIDER='UK Office for National Statistics'
MODELS=('uk-gdp-jeffreys-frequency-v25.1','uk-gdp-regularized-ar1-v25.1')
CACHE=None
RULE='''This market will resolve according to the UK real gross domestic product (GDP) growth rate (% change) for Q{quarter} of {year} compared with the most recent quarter (quarter-on-previous-quarter) in the "GDP first quarterly estimate, UK" release for Q{quarter} of {year}, scheduled for {release}.

The GDP release will be made available here: https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/gdpfirstquarterlyestimateuk/previousreleases

If no data for the specified quarter is released by the date the next quarter's data is scheduled to be released, this market will resolve based on data from the last available quarter.

Note: data from the initial release of the referenced GDP report is what will be used to resolve this market. Data may be revised during the following quarter or as a part of the next estimate's publication, however any revisions to GDP report data made after the initial release will not be considered for this market's resolution.

Note: the resolution source for this market reports GDP growth rates to only one decimal point (e.g. 1.8%). Thus, this is the level of precision that will be used when resolving the market.
'''.removesuffix('\n')


def definitions():
    sha=digest([hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),hashlib.sha256(Path(finance.__file__).read_bytes()).hexdigest()])
    return [{'model_id':name,'model_version':name,'model_sha256':digest([sha,name]),'domain':'economics',
        'feature_version':'observed-ONS-IHYQ-quarterly-growth-v1','hypothesis':hypothesis,
        'input_requirements':['official ONS IHYQ current snapshot before target release','exact firstrelease rules','native fresh executable book'],
        'performance_criteria':['prospective firstrelease proper scores','event-disjoint chronological evaluation'],
        'failure_conditions':['GDP revisions','regime changes','release fallback','correction','small quarterly samples'],
        'risk_assumptions':'Current-vintage conditional research only; no verified training firstreleases or trading authority',
        'source_independence':'Both models share one ONS series; not independent corroboration',
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for name,hypothesis in zip(MODELS,['Jeffreys-smoothed recent-quarter outcome-bin frequency',
                                         'Ridge AR(1) quarterly growth and observed innovation variance'])]


def discovery_queries():return ('UK GDP growth Q3 2026','UK GDP growth Q4 2026')


async def discover(*,clock):return await finance._discover(discovery_queries(),clock=clock)


def supports(market,*,cutoff):
    try:
        now=finance.at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or max(m.timestamp,m.available_at)>now or m.outcome not in {'Yes','No'} or not m.end_time or m.end_time<=now):
            raise ValueError('causal_active_UK_GDP_market_required')
        q=re.fullmatch(r'Will UK GDP growth in Q([1-4]) (20\d{2}) be (negative|between (-?\d+(?:\.\d)?)% and (-?\d+(?:\.\d)?)%|at least (-?\d+(?:\.\d)?)%)\?',m.question)
        date=re.search(r'scheduled for ([A-Z][a-z]+ \d{1,2}, 20\d{2})\.',m.resolution_rules)
        if not q or not date or m.resolution_source!=SOURCE:raise ValueError('exact_UK_GDP_first_release_definition_required')
        quarter,year,tail,lo,hi,threshold=q.groups();quarter,year=int(quarter),int(year)
        release=datetime.strptime(date.group(1),'%B %d, %Y').replace(tzinfo=finance.UTC)
        target=year*4+quarter-1
        if (m.resolution_rules!=RULE.format(quarter=quarter,year=year,release=date.group(1)) or not now<release<=now+timedelta(days=100)
            or release.year*4+(release.month-1)//3<=target):raise ValueError('future_exact_GDP_release_required')
        if tail=='negative':bounds={'tail':'negative','lower':None,'upper':'0'}
        elif tail.startswith('at least'):bounds={'tail':'at_least','lower':threshold,'upper':None}
        else:
            if Decimal(lo)>Decimal(hi):raise ValueError('ordered_GDP_interval_required')
            bounds={'tail':'between','lower':lo,'upper':hi}
        return {'supported':True,'reasons':[],'contract':{'kind':'uk_gdp_qoq_first_release','series_id':'IHYQ','target_period':f'{year} Q{quarter}',
            'quarter':quarter,'year':year,'release_at':release.isoformat(),'release_time_precision':'day_lower_bound_not_exact_publication_time',
            'settlement_at':m.end_time.isoformat(),'source_url':SOURCE,'source_series_url':URL,'selected_outcome':m.outcome,**bounds,
            'market':m.model_dump(mode='json'),'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
            'conditioning':'scheduled firstrelease without fallback/correction; current-vintage historical feature distribution'}}
    except (ValueError,TypeError,KeyError) as error:return {'supported':False,'reasons':[str(error)[:180]],'contract':None}


async def collect(*,clock):
    global CACHE
    now=finance.at(clock())
    if CACHE is not None and 0<=(now-CACHE.available_at).total_seconds()<21600:return (CACHE,)
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        response=await client.get(URL);response.raise_for_status();raw=response.content
    received=finance.at(clock())
    if not 0<len(raw)<=1024**2:raise ValueError('bounded_ONS_source_required')
    payload={'request_url':str(response.url),'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),
        'series_id':'IHYQ','vintage_scope':'current observed snapshot only; historical firstrelease availability not established'}
    CACHE=DomainEvidence(id=digest(['ONS-IHYQ-v25',payload,received.isoformat()]),timestamp=received,available_at=received,retrieved_at=received,
        source=URL,domain='economics',provider=PROVIDER,source_id='IHYQ',payload=payload,content_sha256=digest(payload),
        qualification='qualified_research',independent_of_polymarket=True,missingness=('historical_firstrelease_vintages','calibration','execution_books'))
    return (CACHE,)


def hit(contract,value):
    x=Decimal(str(value)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)
    if contract['tail']=='negative':yes=x<0
    elif contract['tail']=='at_least':yes=x>=Decimal(contract['lower'])
    else:yes=Decimal(contract['lower'])<=x<=Decimal(contract['upper'])
    return yes if contract['selected_outcome']=='Yes' else not yes


def estimates(contract,evidence,*,cutoff):
    now=finance.at(cutoff);mapped=supports(contract['market'],cutoff=now)
    if not mapped['supported'] or mapped['contract']!=contract:raise ValueError('exact_GDP_contract_replay_required')
    e,p=finance.evidence_payload(evidence,url=URL,domain='economics',provider=PROVIDER,series='IHYQ',cutoff=now)
    raw=json.loads(p['raw_response_utf8']);description=raw['description']
    if (description['cdid']!='IHYQ' or description['unit']!='%' or description['datasetId']!='PN2'
        or description['title']!='Gross Domestic Product: Quarter on Quarter growth: CVM SA %'
        or finance.at(description['releaseDate'])>now):raise ValueError('exact_real_seasonal_GDP_qoq_series_required')
    values={};target=contract['year']*4+contract['quarter']-1
    for r in raw['quarters']:
        q=re.fullmatch(r'(\d{4}) Q([1-4])',r['date'])
        if not q:raise ValueError('quarterly_GDP_period_required')
        k=int(q[1])*4+int(q[2])-1;v=float(r['value'])
        if k in values or not math.isfinite(v) or k>=target or finance.at(r['updateDate'])>now:raise ValueError('unique_pre_target_GDP_observations_required')
        values[k]=v
    keys=sorted(values)
    if not 40<=len(keys)<=400 or keys[-1]!=target-1 or keys[-1]-keys[0]+1!=len(keys):raise ValueError('contiguous_GDP_history_through_prior_quarter_required')
    series=[values[k] for k in keys[-40:]];frequency=(.5+sum(hit(contract,x) for x in series))/(1+len(series))
    xs,ys=series[:-1],series[1:];xm,ym=mean(xs),mean(ys)
    beta=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/(sum((x-xm)**2 for x in xs)+1.)
    beta=max(-.95,min(.95,beta));alpha=ym-beta*xm;pred=alpha+beta*series[-1]
    sigma=stdev([y-alpha-beta*x for x,y in zip(xs,ys)])
    if sigma<=0:raise ValueError('nonzero_GDP_innovation_variance_required')
    normal=NormalDist(pred,sigma)
    if contract['tail']=='negative':yes=normal.cdf(-.05)
    elif contract['tail']=='at_least':yes=1-normal.cdf(float(contract['lower'])-.05)
    else:yes=normal.cdf(float(contract['upper'])+.05)-normal.cdf(float(contract['lower'])-.05)
    probability=yes if contract['selected_outcome']=='Yes' else 1-yes;results=[]
    for name,prob in [(MODELS[0],frequency),(MODELS[1],probability)]:
        results.append({'model_id':name,'model_version':name,'model_sha256':next(d['model_sha256'] for d in definitions() if d['model_id']==name),
            'feature_version':'observed-ONS-IHYQ-quarterly-growth-v1','domain':'economics','event_id':contract['market']['event_id'],
            'market_id':contract['market']['market_id'],'token_id':contract['market']['token_id'],'probability':prob,'probability_semantics':'binary_event_probability',
            'lower_probability':0.,'upper_probability':1.,'uncertainty':1.,'training_observations':len(series),'last_source_period':description['date'],
            'dataset_sha256':digest(p),'evidence_ids':[e.id],'evidence_cutoff':now.isoformat(),'event_end_time':contract['release_at'],
            'rules_sha256':contract['rules_sha256'],'contract':contract,'source_lineages':['ONS:IHYQ:current-vintage'],
            'calibration_status':'unvalidated_research','target_conditioning':contract['conditioning'],'unconditional_contract_probability':False,
            'market_probability':None,'limitations':['Revised current-vintage history is a forecasting feature, never asserted as historical firstrelease labels',
            'Scheduled release day is a conservative lower time bound, not independently verified release-hour calendar',
            'No proven calibration, executable edge or regime robustness'],
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return results


async def forecast(market,book,*,clock):
    m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market);mapped=supports(m,cutoff=clock())
    if not mapped['supported']:return {'forecasts':[],'evidence':[],'rejections':mapped['reasons']}
    evidence=()
    try:
        evidence=await collect(clock=clock);cutoff=finance.at(clock());results=estimates(mapped['contract'],evidence,cutoff=cutoff)
        b=await finance.fresh_book(m,book,clock);created=finance.at(clock())
        return {'forecasts':finance.bind_predictions(results,m,b,created),'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[]}
    except (ValueError,TypeError,KeyError,httpx.HTTPError,TimeoutError) as error:
        return {'forecasts':[],'evidence':[e.model_dump(mode='json') for e in evidence],'rejections':[str(error)[:180]]}


def replay(forecast,evidence,*,as_of):
    f=forecast;created=finance.at(f['timestamp']);cutoff=finance.at(f['evidence_cutoff'])
    if not cutoff<=created<=finance.at(as_of):raise ValueError('prospective_economic_cutoff_required')
    if digest(f['market'])!=digest(f['contract']['market']):raise ValueError('exact_forecast_market_contract_binding_required')
    expected=next(r for r in estimates(f['contract'],evidence,cutoff=cutoff) if r['model_id']==f['model_id'])
    for k,v in expected.items():
        if digest(f.get(k))!=digest(v):raise ValueError('GDP_model_replay_mismatch:'+k)
    m=MarketSnapshot.model_validate(f['market']);b=finance.OrderBookSnapshot.model_validate(f['book']);bound=finance.bind_predictions([expected],m,b,created)[0]
    finance.replay_book_provenance(f,m,b,created)
    if f['book_id']!=bound['book_id'] or f['book_sha256']!=bound['book_sha256'] or f['market_expected_payout']!=bound['market_expected_payout']:
        raise ValueError('native_GDP_book_binding_mismatch')
    return {'verified':True,'model_id':f['model_id'],'dataset_sha256':f['dataset_sha256'],'research_only':True,'trading_authority':False,'certification_authority':False}


def bulletin_url(contract):
    slug={1:'januarytomarch',2:'apriltojune',3:'julytoseptember',4:'octobertodecember'}[contract['quarter']]+str(contract['year'])
    return SOURCE.rsplit('/',1)[0]+'/'+slug


def parse_bulletin(contract,raw,*,available_at):
    if not 0<len(raw)<=2*1024**2:raise ValueError('bounded_ONS_firstrelease_bulletin_required')
    text=raw.decode()
    published_metadata=re.findall(r'"datePublished":\s*"([^"]+)"',text)
    modified_metadata=re.findall(r'"dateModified":\s*"([^"]+)"',text)
    if (len(set(published_metadata))!=1 or set(published_metadata)!=set(modified_metadata)
        or finance.at(published_metadata[0])>finance.at(available_at)):
        raise ValueError('unchanged_original_ONS_publication_metadata_required')
    text=re.sub(r'<script\b.*?</script>',' ',text,flags=re.DOTALL|re.IGNORECASE)
    text=html.unescape(re.sub('<[^>]*>',' ',text));text=re.sub(r'\s+',' ',text)
    if re.search(r'correction|corrected',text,re.IGNORECASE):raise ValueError('ONS_corrected_release_requires_review')
    date=re.search(r'Release date: (\d{1,2} [A-Z][a-z]+ 20\d{2})',text)
    if not date:raise ValueError('ONS_firstrelease_publication_date_required')
    published=datetime.strptime(date[1],'%d %B %Y').replace(tzinfo=finance.UTC)
    if not finance.at(contract['release_at'])==published<=finance.at(available_at):raise ValueError('causal_ONS_release_day_required')
    pattern=r'UK real gross domestic product \(GDP\) is estimated to have (increased|decreased|fallen|grown) by (\d+\.\d)% in Quarter '+str(contract['quarter'])+r' \([^)]*\) '+str(contract['year'])
    values={float(m[2])*(-1 if m[1] in {'decreased','fallen'} else 1) for m in re.finditer(pattern,text)}
    if len(values)!=1:raise ValueError('unique_exact_target_GDP_headline_required')
    value=next(iter(values));return {'value':value,'expected':int(hit(contract,value)),'publication_day_lower_bound':published.isoformat()}


async def verify_outcome(forecast,*,directory,clock):
    from neraium_poly.research.phase12.contracts import SettlementProofReference
    from neraium_poly.research.phase12.outcome_collector import (
        acquire_verified_outcome,
        verify_collected_outcome,
    )
    f=forecast;c=f['contract'];now=finance.at(clock())
    if now<finance.at(c['release_at']):return {'verified':False,'reason':'ONS_target_firstrelease_not_due'}
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:response=await client.get(bulletin_url(c))
    if response.status_code!=200:return {'verified':False,'reason':'official_target_ONS_bulletin_unavailable'}
    raw=response.content;observed=finance.at(clock());final=parse_bulletin(c,raw,available_at=observed)
    m=MarketSnapshot.model_validate(f['market']);ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],timestamp=finance.at(f['timestamp']),evidence_cutoff=finance.at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    directory=Path(directory);location=directory/(now.strftime('%Y%m%dT%H%M%S%fZ')+'-'+f['id'][:12]);proof=await acquire_verified_outcome(ref,m,location,clock=clock)
    if proof is None or not verify_collected_outcome(proof,m,ref,directory) or proof.payout!=final['expected'] or proof.settled_at<finance.at(final['publication_day_lower_bound']):
        return {'verified':False,'reason':'native_GDP_finality_and_ONS_firstrelease_corroboration_pending'}
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'outcome':final['expected'],'resolved_at':proof.settled_at.isoformat(),
        'available_at':finance.at(clock()).isoformat(),'proof':proof.model_dump(mode='json'),'evidence':[{'source_url':str(response.url),
        'raw_response_utf8':raw.decode(),'raw_response_sha256':hashlib.sha256(raw).hexdigest(),'retrieved_at':observed.isoformat()}],
        'trading_authority':False,'certification_authority':False}


def replay_outcome(result,study,forecast,*,evidence_root,as_of):
    from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
    from neraium_poly.research.phase12.outcome_collector import verify_collected_outcome
    f=forecast;now=finance.at(as_of)
    if result.get('forecast_id')!=f['id'] or result.get('event_id')!=f['event_id'] or not finance.at(result['available_at'])<=now:raise ValueError('exact_GDP_outcome_identity_required')
    if sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study['forecasts'])!=1 or not finance.at(f['timestamp'])<=finance.at(study['available_at'])<=now:
        raise ValueError('immutable_GDP_forecast_membership_required')
    replay(f,study['evidence'],as_of=now);evidence=result['evidence']
    if len(evidence)!=1:raise ValueError('one_exact_ONS_bulletin_required')
    e=evidence[0];raw=e['raw_response_utf8'].encode();available=finance.at(e['retrieved_at'])
    if e['source_url']!=bulletin_url(f['contract']) or hashlib.sha256(raw).hexdigest()!=e['raw_response_sha256'] or available>finance.at(result['available_at']):raise ValueError('ONS_final_source_hash_or_time_mismatch')
    final=parse_bulletin(f['contract'],raw,available_at=available);m=MarketSnapshot.model_validate(f['market']);proof=VerifiedEventOutcome.model_validate(result['proof'])
    ref=SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],timestamp=finance.at(f['timestamp']),evidence_cutoff=finance.at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    if (not verify_collected_outcome(proof,m,ref,Path(evidence_root)) or proof.payout!=final['expected'] or result['outcome']!=proof.payout
        or not max(finance.at(f['timestamp']),finance.at(study['available_at']),finance.at(final['publication_day_lower_bound']))<proof.settled_at<=proof.available_at<=finance.at(result['available_at'])
        or finance.at(result['resolved_at'])!=proof.settled_at):raise ValueError('ONS_and_native_GDP_finality_mismatch')
    p=f['probability'];y=final['expected'];likelihood=p if y else 1-p
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],'rules_sha256':f['rules_sha256'],
        'outcome':y,'resolved_at':proof.settled_at.isoformat(),'available_at':result['available_at'],'brier':(p-y)**2,
        'log_loss':-math.log(likelihood) if likelihood>0 else None,'market_brier':None,'score_scope':'conditional firstrelease descriptive score, not unconditional market superiority',
        'evidence_sha256':digest(evidence),'reviewed_dependency_group':None,'trading_authority':False,'certification_authority':False}
