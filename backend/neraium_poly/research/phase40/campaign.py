"""Compose existing forecasts, depth economics and shadow accounting, not a broker.

Run with ``python -m neraium_poly.research.phase40.campaign OUTPUT``. Original
source records and every decision are retained locally. No service management,
wallet, account, order-admission, or permissive proof callback is imported.
"""
import argparse
import asyncio
import importlib
import json
import os
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import EventStore, assess_book
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.fees import AuditedFeeAdapter
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase23.continuous import ChallengerResearch
from neraium_poly.research.phase23.outcomes import ChallengerOutcomes
from neraium_poly.research.phase24.continuous import DomainResearch, at
from neraium_poly.research.phase24.outcomes import DomainOutcomes, replay_domain_outcome
from neraium_poly.research.phase25.dependencies import bound_forecasts
from neraium_poly.research.phase28.execution import analyze_depth
from neraium_poly.research.phase28.findings import build_economic_findings
from neraium_poly.research.phase28.shadow import ShadowResearch
from neraium_poly.research.phase29.costs import replay_fee

FEED='http://127.0.0.1:18742/api/market-frame'
FLOOR=100*1024**3
BUDGET=128*1024**2


class CampaignEvidence(Record):
    operation:str
    payload:dict
    previous_record_id:str|None=None
    previous_record_sha256:str|None=None
    research_only:bool=True
    trading_authority:bool=False


class ModelRouter:
    """Route frozen models by exact support/registered model ID, never keywords."""
    __file__=__file__
    def __init__(self,*paths):self.models=[importlib.import_module(p) for p in paths]
    def definitions(self):return [d for m in self.models for d in m.definitions()]
    def supports(self,market,*,cutoff):
        results=[m.supports(market,cutoff=cutoff) for m in self.models];yes=[r for r in results if r.get('supported')]
        if len(yes)==1:return yes[0]
        return {'supported':False,'reasons':['ambiguous_exact_contract_route'] if yes else [x for r in results for x in r.get('reasons',[])]}
    def _model(self,f):
        found=[m for m in self.models if any(d['model_id']==f['model_id'] for d in m.definitions())]
        if len(found)!=1:raise ValueError('unique frozen source model required')
        return found[0]
    async def forecast(self,m,b,*,clock):
        found=[x for x in self.models if x.supports(m,cutoff=at(clock())).get('supported')]
        if len(found)!=1:raise ValueError('unique exact contract source required')
        return await found[0].forecast(m,b,clock=clock)
    def replay(self,f,evidence,*,as_of):return self._model(f).replay(f,evidence,as_of=as_of)
    async def verify_outcome(self,f,**kwargs):return await self._model(f).verify_outcome(f,**kwargs)
    def replay_outcome(self,result,study,f,**kwargs):return self._model(f).replay_outcome(result,study,f,**kwargs)


def adapters():
    return {'weather':ModelRouter('neraium_poly.research.phase25.weather','neraium_poly.research.phase35.weather'),
        'economics':ModelRouter('neraium_poly.research.phase25.economics','neraium_poly.research.phase24.economics'),
        'finance':ModelRouter('neraium_poly.research.phase25.finance'),
        'sports':ModelRouter('neraium_poly.research.phase25.sports','neraium_poly.research.phase24.sports')}


class CampaignOutcomes(DomainOutcomes):
    def __init__(self,*args,models,**kwargs):self.models=models;super().__init__(*args,**kwargs)
    def _module(self,name):
        if name=='sports':
            from neraium_poly.research.phase26.routing import SportsProofs
            return SportsProofs(self.models[name])
        return self.models[name]
    def _replay(self,*args,**kwargs):return replay_domain_outcome(*args,modules=self.models,**kwargs)


def inventory(frame, models, *, now):
    """Every outcome token receives a decision; market/event counts stay distinct."""
    books={b['token_id']:OrderBookSnapshot.model_validate(b) for b in frame['books']};rows=[]
    for raw in frame['markets']:
        m=MarketSnapshot.model_validate(raw);b=books.get(m.token_id);supported=[];why={}
        for name,model in models.items():
            result=model.supports(m,cutoff=now)
            if result.get('supported'):supported.append(name)
            else:why[name]=result.get('reasons', ['unsupported_exact_contract'])
        from neraium_poly.research.phase23.models import map_challenger_contract
        crypto=map_challenger_contract(m,now=now)
        if crypto.compatible and not crypto.review_required:supported.append('crypto')
        else:why['crypto']=list(crypto.reasons)
        quality=list(assess_book(b,now,max_spread=.05,expected_token=m.token_id).reasons) if b else ['current_book_missing']
        if b and b.market_id!=m.market_id:quality.append('book_market_identity_mismatch')
        rows.append({'market_id':m.market_id,'event_id':m.event_id,'token_id':m.token_id,'question':m.question,
            'outcome':m.outcome,'resolution_rules':m.resolution_rules,'resolution_source':m.resolution_source,
            'end_time':m.end_time.isoformat() if m.end_time else None,'supported_adapters':supported,'adapter_rejections':why,
            'book_id':b.id if b else None,'book_at':b.timestamp.isoformat() if b else None,
            'bid':b.bids[0].price if b and b.bids else None,'ask':b.asks[0].price if b and b.asks else None,
            'displayed_ask_notional':sum(p.price*p.size for p in b.asks) if b else None,
            'book_rejections':quality,'decision':'unqualified','fair_probability':None,'recommended_notional':0.,
            'reason':'independent_current_forecast_required' if supported else 'no_supported_independent_model_for_exact_contract'})
    return rows


def scenario(f, book, fee, *, now):
    """Known-fee sensitivity, explicitly NOT verified all-in net EV or a fill."""
    if book.market_id!=f['market_id'] or book.token_id!=f['token_id'] or not assess_book(book,now,max_spread=.05,expected_token=f['token_id']).healthy:
        raise ValueError('fresh exact executable book required for scenario')
    p=f['probability'];conditional=(f.get('unconditional_contract_probability') is not True or f.get('target_conditioning') or f.get('conditioning'))
    lower=f.get('lower_probability',0.) if f.get('calibration_status')=='validated' and not conditional else 0.
    upper=f.get('upper_probability',1.) if lower else 1.
    verified=fee.get('status')=='verified_current_protocol_curve'
    fee_bound=max((fee['rate']*x.price*(1-x.price) for x in book.asks),default=0.) if verified else None
    analyses=[]
    for extra in (0.,.01,.03):
        a=analyze_depth(book,as_of=now,expected_payout=p,lower_payout=lower,upper_payout=upper,
            fee_per_share=fee_bound,slippage_per_share=extra,max_capital=5.,settlement_cost_per_share=None)
        analyses.append({'assumed_extra_slippage_per_share':extra,'analysis':a})
    return {'forecast_id':f['id'],'model_id':f.get('model_id',f.get('model_version')),'probability':p,
        'probability_uncertainty':f.get('uncertainty'),'calibration_status':f.get('calibration_status'),
        'conditional_reference_probability':bool(conditional),'native_payout_bounds':[lower,upper],
        'evidence_ids':f.get('evidence_ids',[]),'source_lineages':f.get('source_lineages',[]),
        'timestamp':f['timestamp'],'book_id':book.id,'book_sha256':digest(book.model_dump(mode='json')),
        'forecast_current':0<=(at(now)-at(f['timestamp'])).total_seconds()<=300,
        'native_fee_proof':fee,'intended_research_notional':5.,'sensitivity':analyses,
        'conservative_all_in_net_ev':None,'recommended_notional':0.,'qualified':False,
        'reasons':['independent_event_disjoint_calibration_and_complete_cost_proof_required',
            *([] if 0<=(at(now)-at(f['timestamp'])).total_seconds()<=300 else ['forecast_stale_at_new_evaluation']),
            *(['conditional_reference_is_not_unconditional_token_value'] if conditional else []),
            *([] if verified else ['native_fee_source_unverified'])],
        'scope':'displayed-depth hypotheses; fees bounded across levels; spread already paid through asks; no assumed fills'}


def replay_model(study,f,sources,*,now):
    if f.get('adapter') in sources:
        proof=sources[f['adapter']].replay(f,study['evidence'],as_of=now)
        if not isinstance(proof,dict) or proof.get('verified') is not True:raise ValueError('model_source_replay_failed')
    else:
        from neraium_poly.research.phase23.outcomes import replay_forecast
        # This validator returns (market, contract, settlement reference), not
        # a verification dictionary. Failure raises; no caller-supplied flags.
        market,contract,_reference=replay_forecast(study,f,as_of=now)
        if market.token_id!=f['token_id'] or market.market_id!=f['market_id'] or contract.rules_sha256!=f['rules_sha256']:
            raise ValueError('crypto source replay identity mismatch')


def outcome_status(domains,crypto):
    verified=set(domains.state['verified'])|set(crypto.state['verified_ids'])
    pending=(set(domains.state['pending'])|set(crypto.state['registered']))-verified
    return {'pending_forecasts':len(pending),'verified_forecasts':len(verified),
        'domains':domains.status(),'crypto':crypto.status(),'reviewed_independent_groups':0,
        'official_event_result_is_not_native_payout':True}


def forecast_performance(store,outcomes,*,now):
    from neraium_poly.research.phase24.evaluation import evaluate, replay_nfl_outcome
    def verify(row,f):
        original=store.get(row['original_study_id'])
        if original is None:raise ValueError('original prospective study required')
        study=json.loads(original[1])
        if row['adapter']=='legacy_nfl':return replay_nfl_outcome(row,study,f,evidence_root=outcomes.directory/'legacy_nfl',as_of=now)
        return outcomes._replay(row,study,f,evidence_root=outcomes.directory,as_of=now)
    rows=[r for r in store.latest('DomainOutcomeStudy',256) if r['operation']=='outcome_check']
    from neraium_poly.research.phase23.competition import build_leaderboard
    from neraium_poly.research.phase23.outcomes import verify_outcome
    def crypto_verify(row,f):
        original=store.get(row['original_study_id'])
        if original is None:raise ValueError('original crypto study required')
        return verify_outcome(row,json.loads(original[1]),f,evidence_root=outcomes.directory.parent/'crypto-outcomes',as_of=now)
    return {'domains':evaluate(store.latest('DomainResearchStudy',100),rows,as_of=now,outcome_verifier=verify),
        'crypto':build_leaderboard(store.latest('ChallengerStudy',100),store.latest('ChallengerOutcomeStudy',256),as_of=now,outcome_verifier=crypto_verify)}


def render_report(result):
    """Human decision sheet from immutable observations; no model rerun or marks."""
    rows={r['forecast_id']:r for r in result['economic_findings']['findings']}
    ranked=[]
    for s in result['depth_scenarios']:
        a=s['sensitivity'][0]['analysis'];point=a.get('maximum_point_profit') or a.get('maximum_gross_profit') or {}
        headroom=point.get('entry_cost_only_net_profit')
        ranked.append((headroom if isinstance(headroom,(int,float)) else float('-inf'),s,point))
    ranked.sort(key=lambda x:(-x[0],x[1]['forecast_id']))
    lines=['# Live research decision campaign',f"Snapshot: {result['as_of']} (historical decision evidence, not a current quote).",
        f"Markets: {result['markets_evaluated']}; outcome tokens: {result['outcome_tokens_evaluated']}; supported tokens: {result['supported_tokens']}; prospective forecasts: {result['prospective_forecasts']} across {result['forecast_parent_events']} parent events (not reviewed independence).",
        f"Qualified opportunities: {result['qualified_opportunities']}; hypothetical fills: {result['shadow']['hypothetical_fills']}; positions: {result['shadow']['positions']}.",
        'Realized P/L unavailable until verified settlement. Actual accounts are not accessed.','',
        '| Market | Model probability | Quantity | VWAP | Known-entry-cost headroom at $5 | Decision |',
        '|---|---:|---:|---:|---:|---|']
    for _rank,s,p in ranked[:12]:
        market=rows[s['forecast_id']]['market_id']
        question=next((u['question'] for u in result['universe_decisions'] if u['market_id']==market),'')
        question=question[:110].replace('`',"'").replace('|','/').replace('\n',' ')
        lines.append(f"| {market}: `{question}` | {s['probability']:.4f} | {p.get('quantity')} | {p.get('entry_vwap')} | {p.get('entry_cost_only_net_profit')} | UNQUALIFIED: calibration/costs/reference |")
    lines+=['','Headroom is a conditional model scenario after bounded entry costs only. Additional slippage, adverse selection, settlement costs and calibrated native payout uncertainty are missing. It is not all-in net EV, a fill, or demonstrated profit.',
        'Unconditional conservative net EV remains unavailable; recommended positions are zero. All models, source references, source times, books, rules and rejection reasons are in the JSON/append-only ledger.']
    return '\n'.join(lines)+'\n'


async def run(output, *, seconds=120, clock=None, fetch=None, models=None, resume=False, settle_only=False, evaluate_only=False):
    if not 30<=seconds<=300:raise ValueError('campaign duration must be30–300seconds')
    if (settle_only or evaluate_only) and not resume:raise ValueError('existing campaign modes require --resume')
    if os.environ.get('LIVE_TRADING_ENABLED','false').lower()!='false' or os.environ.get('PAPER_TRADING','true').lower()!='true':
        raise ValueError('paper-only research environment required')
    clock=clock or (lambda:datetime.now(UTC));output=Path(output).resolve()
    if resume:
        if not (output/'campaign.sqlite').is_file():raise ValueError('existing isolated campaign required')
    else:output.mkdir(parents=True,exist_ok=False)
    def can_write():
        return shutil.disk_usage(output).free>FLOOR+16*1024**2 and sum(p.stat().st_size for p in output.rglob('*') if p.is_file())<BUDGET-16*1024**2
    if not can_write():raise ValueError('campaign storage admission refused')
    store=EventStore(output/'campaign.sqlite');sources=models if models is not None else adapters()
    deadline=asyncio.get_running_loop().time()+seconds
    def record(operation,payload):
        if not can_write():raise ValueError('campaign evidence budget exhausted')
        previous=store.connection.execute("SELECT id,digest FROM events WHERE kind='CampaignEvidence' ORDER BY rowid DESC LIMIT 1").fetchone()
        parent,checksum=previous if previous else (None,None)
        now=at(clock());row=CampaignEvidence(id=digest([operation,now.isoformat(),payload,parent,checksum]),
            timestamp=now,available_at=now,source='neraium-poly/operator-campaign/v40',operation=operation,payload=payload,
            previous_record_id=parent,previous_record_sha256=checksum)
        if len(row.model_dump_json().encode())>8*1024**2:raise ValueError('campaign record byte limit exceeded')
        store.append(row)
    async with httpx.AsyncClient(timeout=8,trust_env=False) as client:
        async def get_frame():
            value=await fetch() if fetch else (await client.get(FEED)).raise_for_status().json()
            value=SharedMarketFrame.model_validate(value).model_dump(mode='json')
            if len(value['markets'])>4096 or len(value['books'])>4096:raise ValueError('bounded live universe required')
            if any(len({r['token_id'] for r in value[k]})!=len(value[k]) for k in ('markets','books')):raise ValueError('unique live identities required')
            if value.get('mode')!='real_market_data' or value.get('producer_health',{}).get('status')!='ok':raise ValueError('healthy genuine market frame required')
            now=at(clock())
            if not 0<=(now-at(value['available_at'])).total_seconds()<=15:raise ValueError('fresh market frame required')
            record('market_snapshot',value);return value
        fee_adapter=AuditedFeeAdapter(store,can_write,clock=clock)
        # Evaluation can resume a failed report without resetting or re-enrolling
        # its immutable model checkpoint after an orchestration source repair.
        domains=None if evaluate_only or settle_only else DomainResearch(store,clock=clock,can_write=can_write,adapters=sources)
        crypto=None if evaluate_only or settle_only else ChallengerResearch(store,clock=clock,can_write=can_write)
        shadow=ShadowResearch(store,clock=clock,can_write=can_write)
        outcomes=CampaignOutcomes(store,output/'outcomes',clock=clock,can_write=can_write,models=sources)
        crypto_outcomes=ChallengerOutcomes(store,output/'crypto-outcomes',clock=clock,can_write=can_write)
        errors=[];timed_out=False
        try:
            if settle_only:
                async with asyncio.timeout(seconds):
                    await outcomes.step();await crypto_outcomes.step()
                result={'outcomes':outcome_status(outcomes,crypto_outcomes),'forecast_performance':forecast_performance(store,outcomes,now=at(clock())),
                    'shadow':shadow.status(),'scope':'existing prospective forecasts only; official outcomes are not native payout or trading P/L','research_only':True,'trading_authority':False}
                record('outcome_update',result)
                (output/('outcome-update-'+digest(result)[:16]+'.json')).write_text(json.dumps(result,indent=2)+'\n');return result
            frame=await get_frame();universe=inventory(frame,sources,now=at(clock()));record('universe_decisions',{'rows':universe})
            try:
                async with asyncio.timeout(seconds-15):
                    # Existing engines each bound source concurrency; run sequentially
                    # so this campaign cannot consume more than two source workers.
                    if domains is not None:await domains.step(frame)
                    if crypto is not None:frame=await get_frame();await crypto.step(frame)
            except TimeoutError:timed_out=True;errors.append('source_phase_deadline_reached; committed forecasts retained')
            except (ValueError,OSError,httpx.HTTPError) as error:errors.append(f'{type(error).__name__}:{error}')
            studies=store.latest('DomainResearchStudy',100)+store.latest('ChallengerStudy',100)
            now=at(clock());bound,invalid=bound_forecasts(studies,as_of=now);verified=set();fees={};scenarios=[]
            for identity,item in list(bound.items())[:32]:
                f=item['forecast'];study=item['study']
                try:
                    replay_model(study,f,sources,now=now)
                    verified.add(identity)
                    remaining=deadline-asyncio.get_running_loop().time()-4
                    if remaining<=0:raise TimeoutError('campaign fee collection budget exhausted')
                    async with asyncio.timeout(min(5,remaining)):observation=await fee_adapter.observed_fee(f['token_id'])
                    fees[f['token_id']]=replay_fee(observation,store,token_id=f['token_id'],as_of=at(clock()))
                except (ValueError,TypeError,KeyError,OSError,httpx.HTTPError,TimeoutError) as error:
                    fees[f['token_id']]={'status':'unavailable','reason':f'{type(error).__name__}:{error}'}
            frame=await get_frame();now=at(clock());current={b['token_id']:OrderBookSnapshot.model_validate(b) for b in frame['books']}
            for identity,item in bound.items():
                f=item['forecast'];b=current.get(f['token_id'])
                if b and identity in verified:
                    try:scenarios.append(scenario(f,b,fees.get(f['token_id'],{}),now=now))
                    except ValueError as error:errors.append(f'{identity}:{error}')
            report=build_economic_findings(studies,frame,as_of=now,verified_forecast_ids=verified)
            shadow.step(report,frame)
            await asyncio.sleep(.3)
            next_frame=await get_frame();shadow.step(report,next_frame)
            async with asyncio.timeout(5):
                await outcomes.step();await crypto_outcomes.step()
            rejected=Counter()
            for row in report['findings']:rejected.update(row['reasons'])
            for row in universe:
                predictions=[f for f in report['findings'] if f['token_id']==row['token_id']]
                row['forecast_ids']=[f['forecast_id'] for f in predictions]
                if predictions:
                    row['reason']=';'.join(sorted({reason for f in predictions for reason in f['reasons']}))
                    row['model_estimates']=[{k:f.get(k) for k in ('forecast_id','forecast_probability','scenario_expected_gross_profit','conservative_expected_net_profit','status','reasons')} for f in predictions]
                else:rejected[row['reason']]+=1
            result={'schema_version':'phase40-operator-campaign-v1','as_of':at(clock()).isoformat(),
                'markets_evaluated':len({r['market_id'] for r in universe}),'outcome_tokens_evaluated':len(universe),
                'parent_events':len({r['event_id'] for r in universe}),'supported_tokens':sum(bool(r['supported_adapters']) for r in universe),
                'fresh_executable_tokens':sum(not r['book_rejections'] for r in universe),
                'prospective_forecasts':len(bound),'independent_source_replayed_forecasts':len(verified),
                'forecast_parent_events':len({x['forecast']['event_id'] for x in bound.values()}),
                'reviewed_independent_events':0,'qualified_opportunities':sum(r['qualified_research'] for r in report['findings']),
                'universe_decisions':universe,'economic_findings':report,'depth_scenarios':scenarios,
                'shadow':shadow.status(),'rejections':dict(rejected),'invalid_forecasts':dict(invalid),'errors':errors,
                'outcome_verification':outcome_status(outcomes,crypto_outcomes),
                'forecast_performance':forecast_performance(store,outcomes,now=at(clock())),
                'source_phase_timed_out':timed_out,'verified_settlements_this_campaign':0,
                'limitations':['Unresolved forecasts are not settled performance.','No calibrated all-in proof or candidate/settlement verifier is registered; qualified execution remains withheld.',
                    'Shadow pool is hypothetical; existing accounts are never opened or modified.','Snapshots show capacity, not guaranteed fills.'],
                'research_only':True,'trading_authority':False,'actual_account_access':False}
            record('campaign_report',result)
            path=output/('report-'+digest(result)[:16]+'.json');path.write_text(json.dumps(result,indent=2)+'\n')
            path.with_suffix('.md').write_text(render_report(result))
            return result
        finally:await fee_adapter.close();store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--settle-only',action='store_true')
    parser.add_argument('--evaluate-only',action='store_true')
    args=parser.parse_args();result=asyncio.run(run(args.output,seconds=args.seconds,resume=args.resume,settle_only=args.settle_only,evaluate_only=args.evaluate_only))
    print(json.dumps({k:result[k] for k in ('markets_evaluated','outcome_tokens_evaluated','supported_tokens','prospective_forecasts','qualified_opportunities','errors','outcomes') if k in result}))


if __name__=='__main__':main()
