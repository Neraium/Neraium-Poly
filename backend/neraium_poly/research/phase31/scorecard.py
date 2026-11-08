"""One bounded, source-anchored domain scorecard; never trading authorization."""
from collections import Counter
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.discovery import classify_snapshot
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

DOMAINS=('crypto','finance','economics','weather','sports','politics','geopolitics','technology','science','esports','entertainment','other')


class CPIInputStudy(Record):
    bundle:dict
    qualification:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


class DomainScorecardStudy(Record):
    source_volume_study_id:str
    source_volume_study_sha256:str
    report:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


def build_scorecard(entries,frame,economic,official,shadow,*,as_of,macro=None):
    now=at(as_of);raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
    if raw.get('mode')!='real_market_data' or not at(raw['timestamp'])<=at(raw['available_at'])<=now or (now-at(raw['available_at'])).total_seconds()>15:raise ValueError('scorecard_current_genuine_frame_required')
    if len(entries)>8192 or len(raw['markets'])>4096:raise ValueError('bounded_domain_scorecard_inventory_required')
    groups={d:{'markets_observed':0,'fresh_executable_tokens_at_evaluation':0,'markets_with_fresh_executable_book_at_evaluation':0,
        'prospective_forecasts':0,'source_replayed_forecasts':0,'reviewed_event_groups':0,
        'official_event_forecast_scores':0,'official_event_groups':0,'native_verified_outcomes':0,
        'economic_findings':0,'economic_sensitivities':0,'current_model_scenarios':0,'positive_estimated_gross_scenarios':0,
        'evidence_qualified_positive_net_estimates':0,'positive_estimated_net_scenarios':0,'qualified_paper_opportunities':0,
        'shadow_positions':0 if shadow.get('positions')==0 else None,'shadow_fills':0 if shadow.get('hypothetical_fills')==0 else None,
        'realized_simulated_pnl':None,'drawdown':None,'capital_utilization':0. if shadow.get('positions')==0 and shadow.get('pending_orders')==0 else None,
        'forecast_accuracy':[],'sii_incremental_value':None,'blockers':{},'forecasting_support':'evidence_supported_research_models' if d in ('crypto','finance','economics','weather','sports') else 'evidence_only_no_supported_probability_model'} for d in DOMAINS}
    markets={};books={b['token_id']:b for b in raw['books']};domain_markets={d:set() for d in DOMAINS};fresh_markets={d:set() for d in DOMAINS};classification=Counter()
    for value in raw['markets']:
        d=classify_snapshot(value,now);name=d.domain if d.domain in groups else 'other';markets[value['token_id']]=(name,value)
        domain_markets[name].add(value['market_id']);classification[d.classification_basis]+=1
        b=books.get(value['token_id'])
        if (b is not None and b['source'] in PUBLIC_BOOK_SOURCES and b['market_id']==value['market_id']
            and value['status']=='active' and value.get('end_time') and at(value['end_time'])>now
            and at(b['timestamp'])<=at(b['available_at'])<=now and 0<=(now-at(b['available_at'])).total_seconds()<=15):
            from neraium_poly.contracts import OrderBookSnapshot
            if assess_book(OrderBookSnapshot.model_validate(b),now,max_spread=.05,expected_token=value['token_id']).healthy:
                groups[name]['fresh_executable_tokens_at_evaluation']+=1;fresh_markets[name].add(value['market_id'])
    forecasts={};events={d:set() for d in DOMAINS};conflicts=set()
    for ref in entries:
        if ref.get('type')!='forecast':continue
        fid=ref['forecast_id'];f=ref['forecast']
        if fid in conflicts:continue
        if fid in forecasts:
            if forecasts[fid]['forecast_sha256']!=ref['forecast_sha256']:conflicts.add(fid);forecasts.pop(fid)
            continue
        if max(at(f['timestamp']),at(ref['available_at']))>now:continue
        forecasts[fid]=ref
    for ref in forecasts.values():
        f=ref['forecast'];d=f['domain'] if f['domain'] in groups else 'other';groups[d]['prospective_forecasts']+=1
        groups[d]['source_replayed_forecasts']+=ref.get('replay_verified') is True
        if (ref.get('review') or {}).get('canonical_group_id'):events[d].add(ref['review']['canonical_group_id'])
    for model in official.get('models',[]):
        row_domains={forecasts[x['forecast_id']]['forecast']['domain'] for x in model.get('event_scores',[]) if x['forecast_id'] in forecasts}
        if len(row_domains)!=1:continue
        d=next(iter(row_domains));d=d if d in groups else 'other';gs={x['event_group_id'] for x in model['event_scores']}
        groups[d]['forecast_accuracy'].append({k:model.get(k) for k in ['model_id','descriptive_brier','descriptive_log_loss','neutral_brier','market_baseline_comparison','superiority_established']})
        groups[d].setdefault('_official_groups',set()).update(gs)
        groups[d].setdefault('_scored_forecasts',set()).update(x['forecast_id'] for x in model['event_scores'])
    reasons={d:Counter() for d in DOMAINS}
    for finding in economic.get('findings',[]):
        d=finding.get('domain');d=d if d in groups else 'other';g=groups[d];g['economic_findings']+=1
        pipeline=finding.get('pipeline',{});g['economic_sensitivities']+=bool(pipeline.get('economic_evaluation_completed'))
        g['current_model_scenarios']+=bool(finding.get('execution_analysis'))
        g['positive_estimated_gross_scenarios']+=bool(type(finding.get('scenario_expected_gross_profit')) in (int,float) and finding['scenario_expected_gross_profit']>0)
        # Only independently replayed conservative proofs enter this count.
        g['evidence_qualified_positive_net_estimates']+=finding.get('qualified_research') is True
        g['positive_estimated_net_scenarios']+=bool(type(finding.get('scenario_expected_net_profit')) in (int,float) and finding['scenario_expected_net_profit']>0)
        reasons[d].update(finding.get('reasons',[]))
    for d,g in groups.items():
        g.update(markets_observed=len(domain_markets[d]),markets_with_fresh_executable_book_at_evaluation=len(fresh_markets[d]),reviewed_event_groups=len(events[d]),
            official_event_groups=len(g.pop('_official_groups',set())),official_event_forecast_scores=len(g.pop('_scored_forecasts',set())),blockers=dict(reasons[d].most_common(16)))
    return {'schema_version':'phase31-profitability-scorecard-v1','implementation_sha256':digest([__import__('pathlib').Path(__file__).read_text(),__import__('pathlib').Path(classify_snapshot.__code__.co_filename).read_text()]),'as_of':now.isoformat(),'frame_id':raw['id'],'frame_sha256':digest(raw),
        'domains':groups,'source_forecast_count':len(forecasts),'conflicting_original_ids_quarantined':len(conflicts),
        'classification_provenance':{'source':'existing normalized-snapshot domain classifier; structured source tags may not survive normalization','basis_counts':dict(classification)},
        'coverage_scope':'current primary+bounded supplementary universe, not all discovered historical markets',
        'forecast_scope':'all anchored indexed research registry; legacy Phase12/13 journals separately reconciled, not silently counted here',
        'economic_scope':'one current evaluation; stale-original sensitivities are separate from current model scenarios',
        'event_group_scope':'reviewed common drivers, not statistically independent samples or certified groups',
        'official_metrics_as_of':official.get('as_of'),'macro_readiness':macro,'effective_independent_sample_size':None,'certified_training_events':0,'certified_heldout_events':0,
        'shadow_aggregate':{k:shadow.get(k) for k in ['orders_attempted','hypothetical_fills','positions','capital_utilization','realized_simulated_pnl','drawdown']},
        'sii_paired_events':official.get('sii_paired_events',0),'sii_incremental_value':None,'research_only':True,'trading_authority':False,'certification_authority':False}


class ScorecardPublisher:
    def __init__(self,store,*,clock,can_write,official,macro,shadow):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.official,self.macro,self.shadow=official,macro,shadow;self.report=None;self.record_id=None

    def observe(self,volume,frame,entries):
        import json

        from .macro import macro_readiness
        now=at(self.clock());r=build_scorecard(entries,frame,volume.report,self.official(),self.shadow(),as_of=now,macro=macro_readiness(entries,as_of=now))
        cpi=self.macro()
        stamp=cpi.get('available_at') if isinstance(cpi,dict) else None
        if stamp is not None and not 0<=(now-at(stamp)).total_seconds()<=21600:
            cpi={'status':'stale','last_available_at':stamp,'forecast_probability':None,'trading_authority':False}
        r['cpi_input_qualification']=cpi;r['economic_decision_at']=volume.timestamp.isoformat()
        if len(json.dumps(r,allow_nan=False).encode())>256*1024:raise ValueError('bounded_domain_scorecard_report_required')
        if not self.can_write():raise ValueError('scorecard_archive_backpressure')
        identity=digest(['domain-scorecard-v31',volume.id,r])
        record=DomainScorecardStudy(id=identity,timestamp=now,available_at=now,source='neraium-poly/domain-scorecard/v31',
            source_volume_study_id=volume.id,source_volume_study_sha256=digest(volume.model_dump(mode='json')),report=r)
        self.store.append(record);self.report=r;self.record_id=identity

    def status(self):
        if self.report is None:return {'status':'pending','trading_authority':False,'research_only':True}
        age=(at(self.clock())-at(self.report['as_of'])).total_seconds()
        if not 0<=age<=120:return {'status':'stale','last_report_id':self.record_id,'last_published_at':self.report['as_of'],'trading_authority':False,'research_only':True}
        return {**self.report,'status':'research_only','report_id':self.record_id,'age_seconds':age}
