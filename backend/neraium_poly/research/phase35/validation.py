"""Causal market-baseline preservation and existing native-calibration gates.

A completed reference event does not turn a conditional forecast into a native
payout probability. Original marks remain useful evidence, never substituted
with later prices or silently scored against a different target.
"""
import hashlib
import math
from collections import Counter, defaultdict

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.calibration import SEMANTICS
from neraium_poly.research.phase18.validation import event_disjoint_validation
from neraium_poly.research.phase25.dependencies import at

MAX_ROWS=1024
EPS=1e-12
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False}


def _probability(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('finite_probability_required')
    return value


def _interval(values):
    if not isinstance(values,(list,tuple)) or len(values)!=2:raise ValueError('probability_interval_required')
    low,high=map(_probability,values)
    if low>high:raise ValueError('ordered_probability_interval_required')
    return low,high


def conditional_native_bounds(probability_interval,*,condition_probability_interval=(0.,1.),alternative_payout_interval=(0.,1.)):
    """Total-probability sensitivity, not a fitted interval or native proof.

    For a declared condition C, E[payout]=P(C)*p+(1-P(C))*alternative.
    The caller must independently qualify any narrower ex-ante condition or
    fallback bounds; observed completion afterward is not such evidence.
    """
    ps=_interval(probability_interval);cs=_interval(condition_probability_interval);rs=_interval(alternative_payout_interval)
    corners=[c*p+(1-c)*r for c in cs for p in ps for r in rs]
    return {'native_expected_payout_interval':[min(corners),max(corners)],
        'condition_probability_interval':list(cs),'alternative_payout_interval':list(rs),
        'interval_status':'assumption_sensitivity_not_confidence_interval','ex_ante_condition_evidence_verified':False,
        'market_superiority':None,'qualified_opportunity':False,**AUTHORITY}


def _original_book(forecast,*,created):
    market=MarketSnapshot.model_validate(forecast['market']);book=OrderBookSnapshot.model_validate(forecast['book'])
    if (any(forecast[k]!=getattr(market,k) for k in ('market_id','event_id','token_id'))
        or book.market_id!=market.market_id or book.token_id!=market.token_id or book.exchange!=market.exchange
        or book.source not in PUBLIC_BOOK_SOURCES or forecast['book_id']!=book.id
        or digest(forecast['book'])!=forecast['book_sha256']
        or hashlib.sha256(market.resolution_rules.encode()).hexdigest()!=forecast['rules_sha256']
        or not market.timestamp<=market.available_at<=created
        or not 0<=(created-book.available_at).total_seconds()<=15
        or not assess_book(book,created,max_spread=.05,expected_token=market.token_id).healthy):
        raise ValueError('exact_original_native_book_and_rule_binding_required')
    midpoint=(book.bids[0].price+book.asks[0].price)/2
    declared=forecast.get('market_expected_payout',forecast.get('market_probability'))
    if abs(_probability(declared)-midpoint)>EPS:raise ValueError('contemporaneous_original_midpoint_mismatch')
    return market,book,midpoint


def audit_market_baselines(records,*,as_of,forecast_verifier=None):
    """Audit full original studies/forecasts with the existing model replay callback.

    records yields {'study': original study, 'forecast': original full forecast}.
    forecast_verifier follows phase26.reporting.callbacks()[0], including exact
    original study and forecast hashes. Inputs are consumed one at a time;
    only compact baseline provenance is retained. No native labels are invented.
    """
    now=at(as_of);accepted={};conflicted=set();rejected=Counter();inputs=0
    for item in records:
        inputs+=1
        if inputs>MAX_ROWS:raise ValueError('bounded_market_baseline_inventory_required')
        try:
            study,f=item['study'],item['forecast'];created=at(f['timestamp']);published=at(study['available_at'])
            if (study.get('trading_authority') is not False or study.get('certification_authority') is not False
                or not at(f['evidence_cutoff'])<=created<=published<=now
                or not created<at(f['event_end_time'])
                or sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study.get('forecasts',[]))!=1):
                raise ValueError('original_prospective_forecast_membership_required')
            if not callable(forecast_verifier):raise TypeError('independent_original_model_replay_required')
            try:proof=forecast_verifier(study,f,as_of=now)
            except Exception as error:raise ValueError('original_model_replay_failed') from error
            if (not isinstance(proof,dict) or proof.get('verified') is not True
                or proof.get('forecast_sha256')!=digest(f) or proof.get('original_study_sha256')!=digest(study)):
                raise ValueError('independent_original_model_replay_required')
            market,book,midpoint=_original_book(f,created=created);p=_probability(f['probability'])
            low,high=_interval([f['lower_probability'],f['upper_probability']])
            if not low<=p<=high:raise ValueError('forecast_probability_outside_declared_interval')
            conditioning=f.get('target_conditioning') or f.get('conditioning')
            comparable=(f.get('unconditional_contract_probability') is True and not conditioning
                and f.get('probability_semantics') in (SEMANTICS,'binary_event_probability')
                and f.get('market_probability') is not None and abs(_probability(f['market_probability'])-midpoint)<=EPS)
            reasons=[] if comparable else ['conditional_or_unreviewed_native_payout_semantics']
            sensitivity=conditional_native_bounds([low,high]) if not comparable else None
            row={'forecast_id':f['id'],'forecast_sha256':digest(f),'original_study_id':study['id'],
                'original_study_sha256':digest(study),'domain':f['domain'],'model_id':f['model_id'],
                'model_version':f['model_version'],'model_sha256':f['model_sha256'],
                'event_id':market.event_id,'market_id':market.market_id,'token_id':market.token_id,
                'rules_sha256':f['rules_sha256'],'forecast_at':created.isoformat(),'recorded_at':published.isoformat(),
                'evidence_cutoff':at(f['evidence_cutoff']).isoformat(),'book_id':book.id,
                'book_sha256':f['book_sha256'],'market_at':book.timestamp.isoformat(),
                'market_available_at':book.available_at.isoformat(),'bid':book.bids[0].price,'ask':book.asks[0].price,
                'market_expected_payout_midpoint':midpoint,'model_probability':p,'model_interval':[low,high],
                'conditioning':conditioning,'probability_semantics':f['probability_semantics'],
                'native_probability_semantics_comparable':comparable,'paired_brier':None,'paired_log_loss':None,
                'comparison_rejections':reasons,'native_sensitivity':sensitivity,**AUTHORITY}
            key=f['id']
            if key in conflicted:raise ValueError('conflicting_original_forecast_identity')
            if key in accepted:
                if accepted[key]['forecast_sha256']!=row['forecast_sha256']:
                    conflicted.add(key);accepted.pop(key);raise ValueError('conflicting_original_forecast_identity')
                rejected['repeated_original_forecast_not_independent']+=1
                if at(accepted[key]['recorded_at'])<=published:continue
            accepted[key]=row
        except (ValueError,KeyError,TypeError,OverflowError,OSError) as error:rejected[str(error)[:160]]+=1
    rows=sorted(accepted.values(),key=lambda r:(r['forecast_at'],r['forecast_id']));models=defaultdict(list)
    for row in rows:models[(row['domain'],row['model_id'],row['model_version'],row['model_sha256'])].append(row)
    leaderboard=[{'domain':key[0],'model_id':key[1],'model_version':key[2],'model_sha256':key[3],
        'original_forecasts':len(group),'original_market_baselines_preserved':len(group),
        'native_semantics_comparable':sum(r['native_probability_semantics_comparable'] for r in group),
        'brier_vs_market':None,'log_loss_vs_market':None,'calibration':None,'market_superiority':None,
        'status':('awaiting_native_target_qualified_outcomes' if any(r['native_probability_semantics_comparable'] for r in group) else 'conditional_target_not_native_comparable'),'rank':None,**AUTHORITY} for key,group in sorted(models.items())]
    return {'schema_version':'phase35-original-market-baseline-audit-v1','as_of':now.isoformat(),
        'input_rows':inputs,'exact_original_market_baselines':len(rows),
        'native_semantics_comparable_forecasts':sum(r['native_probability_semantics_comparable'] for r in rows),
        'native_verified_pairs':0,'event_disjoint_heldout_groups':0,'models':leaderboard,
        'baselines':rows[:64],'baseline_sample_limit':64,'rejections':dict(rejected),
        'comparison_scope':'Original expected-payout quote preserved; conditional reference forecasts are never relabelled as unconditional native probabilities',
        'metrics':None,'calibration':None,'market_superiority':None,'execution_cost_adjusted_performance':None,**AUTHORITY}


def validate_native_market_rows(rows,*,training_end,heldout_start,as_of,verify_row=None):
    """Use the existing 100/100 calibration contract after exact native replay.

    Caller verify_row must independently replay the original forecast/model,
    native settlement, dependency review and predeclared split. Flags alone do
    not authenticate rows. Reference-event labels must never be adapted here.
    """
    def verify(row):
        if (row.get('native_payout_verified') is not True or row.get('unconditional_contract_probability') is not True
            or row.get('target_conditioning') or row.get('conditioning')):
            raise ValueError('unconditional_native_payout_and_forecast_required')
        if not at(row['split_declared_at'])<=at(heldout_start):raise ValueError('predeclared_heldout_boundary_required')
        if row.get('split')=='heldout' and not at(row['split_declared_at'])<=at(row['forecast_at']):raise ValueError('postselection_split_declaration')
        b=OrderBookSnapshot.model_validate(row['market_book']);created=at(row['forecast_at'])
        if (row['market_book_sha256']!=digest(row['market_book']) or b.market_id!=row['market_id'] or b.token_id!=row['token_id']
            or b.source not in PUBLIC_BOOK_SOURCES or not assess_book(b,created,max_spread=.05,expected_token=b.token_id).healthy
            or at(row['market_at'])!=b.timestamp or at(row['market_available_at'])!=b.available_at
            or not 0<=(created-b.available_at).total_seconds()<=15
            or abs(_probability(row['market_probability'])-(b.bids[0].price+b.asks[0].price)/2)>EPS):
            raise ValueError('exact_contemporaneous_native_market_baseline_required')
        if not callable(verify_row) or verify_row(row) is not True:raise ValueError('independent_native_raw_replay_required')
        return True
    result=event_disjoint_validation(rows,training_end=training_end,heldout_start=heldout_start,cutoff=as_of,verify_row=verify)
    # Existing individual Hoeffding intervals become simultaneous family bounds.
    count=len(result['cohorts'])
    for cohort in result['cohorts']:
        metrics=cohort['calibration']['metrics']
        if metrics is not None:
            radius=math.sqrt(2*math.log(40*max(1,count))/metrics['heldout_events']);delta=metrics['paired_brier_difference']
            metrics['paired_brier_difference_95_bound']=[max(-1,delta-radius),min(1,delta+radius)]
            metrics['interval_method']='Bonferroni-adjusted Hoeffding bound across evaluated homogeneous cohorts; assumes independent reviewed groups'
            metrics['forecasting_superiority_supported']=metrics['paired_brier_difference_95_bound'][1]<0
    return {**result,'schema_version':'phase35-native-market-relative-validation-v1','multiple_testing_cohorts':count,
        'native_payout_verified_scope':'per row independently replayed; not automatic certification',
        'market_baseline':'exact prospective native bid/ask midpoint; not executable acquisition price',
        'execution_cost_adjusted_performance':None,**AUTHORITY}
