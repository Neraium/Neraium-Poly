"""Prospective official-event scoring; never a native settlement/account label."""
import asyncio
import math
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.data.connectivity import _payload_bytes
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase25.dependencies import at


class EventScoringEnrollment(Record):
    policy:dict
    research_only:Literal[True]=True
    native_payout_verified:Literal[False]=False
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


class OfficialEventLabelStudy(Record):
    enrollment_id:str
    original_study_id:str
    original_study_sha256:str
    original_forecast_sha256:str
    forecast_id:str
    source_anchor:dict
    result:dict
    replay:dict
    research_only:Literal[True]=True
    native_payout_verified:Literal[False]=False
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


class EventScoreSnapshot(Record):
    enrollment_id:str
    source_anchor:dict
    report:dict
    research_only:Literal[True]=True
    native_payout_verified:Literal[False]=False
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


def _body(raw):
    if isinstance(raw,dict):return raw
    import hashlib
    import json
    if hashlib.sha256(raw[1].encode()).hexdigest()!=raw[2]:raise ValueError('event_score_record_hash_mismatch')
    return json.loads(raw[1])


async def _thread(function,*args,**kwargs):
    worker=asyncio.create_task(asyncio.to_thread(function,*args,**kwargs))
    try:return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await asyncio.gather(worker,return_exceptions=True)
        raise


def _scoring_forecast(f):
    # Raw source/model/book evidence stays in its original immutable journal.
    return {k:f[k] for k in ('id','model_id','market_id','token_id','timestamp','event_end_time','probability','domain','rules_sha256')}


def evaluation(labels):
    """Earliest prospective prediction per official game/model, no pooled tokens.

    Completion-conditioned NHL probabilities cannot be compared with unconditional
    Polymarket marks. Native payout and certified calibration remain unverified.
    Small samples retain descriptive proper scores, never superiority/authority.
    """
    picked={};rejected=Counter();valid_labels=set()
    for item in labels:
        try:
            f,p=item['forecast'],item['proof']
            if (p.get('event_result_verified') is not True or p.get('native_payout_verified') is not False
                or p.get('trading_authority') is not False or p.get('certification_authority') is not False
                or p.get('forecast_id')!=f['id'] or p.get('market_id')!=f['market_id'] or p.get('token_id')!=f['token_id']):
                raise ValueError('exact_replayed_official_event_label_required')
            if not at(f['timestamp'])<=at(item['forecast_available_at'])<at(f['event_end_time'])<=at(p['event_end_lower']):raise ValueError('prospective_event_label_cutoff_required')
            probability=f['probability'];outcome=p['outcome']
            if (type(probability) not in (int,float) or not math.isfinite(probability) or not 0<=probability<=1
                or type(outcome) not in (int,float) or outcome not in (0,1)):raise ValueError('finite_binary_event_probability_required')
            valid_labels.add((item['label_id'],f['id']))
            key=(p['event_group_id'],f['model_id'])
            if key in picked:
                old=picked[key]
                if old['forecast']['market_id']!=f['market_id'] or old['forecast']['token_id']!=f['token_id']:
                    rejected['multiple_contracts_per_model_event_not_independent']+=1
                if (at(f['timestamp']),f['id'])>=(at(old['forecast']['timestamp']),old['forecast']['id']):continue
            picked[key]=item
        except (ValueError,KeyError,TypeError) as e:rejected[str(e)[:120]]+=1
    models=defaultdict(list)
    for (group,model),item in picked.items():
        f,p=item['forecast'],item['proof'];prob=f['probability'];y=p['outcome']
        loss=-(math.log(prob) if y else math.log1p(-prob)) if 0<prob<1 else 0. if prob==y else None
        models[model].append({'forecast_id':f['id'],'event_group_id':group,'forecast_probability':prob,
            'outcome':y,'brier':(prob-y)**2,'log_loss':loss,'log_loss_status':'infinite' if loss is None else 'finite',
            'market_brier':None,'market_log_loss':None,'neutral_brier':.25,
            'label_id':item['label_id'],'official_evidence_sha256':p['official_evidence_sha256']})
    result=[]
    for model,rows in sorted(models.items()):
        n=len(rows);finite=all(r['log_loss'] is not None for r in rows)
        result.append({'model_id':model,'event_disjoint_official_games':n,'descriptive_brier':sum(r['brier'] for r in rows)/n,
            'descriptive_log_loss':sum(r['log_loss'] for r in rows)/n if finite else None,
            'log_loss_status':'finite' if finite else 'infinite','neutral_brier':.25,
            'market_baseline_comparison':None,'confidence_intervals':None,'calibration':None,'superiority_established':False,
            'reason':'completion-conditioned target; insufficient event-disjoint evaluation for calibration or superiority',
            'event_scores':rows,'research_only':True,'trading_authority':False,'certification_authority':False})
    return {'status':'official_event_research','schema_version':'phase30-official-event-scores-v1','verified_forecast_labels':len(valid_labels),
        'scored_forecast_event_model_pairs':len(picked),'distinct_official_games':len({g for g,_ in picked}),'statistical_independence_verified':False,'effective_independent_sample_size':None,
        'models':result,'rejections':dict(rejected),'market_superiority':None,'native_verified_outcomes':0,
        'certified_training_events':0,'certified_heldout_events':0,'sii_paired_events':0,'sii_incremental_value':None,
        'realized_simulated_pnl':None,'scope':'official completed event research only; not verified Polymarket payout, native settlement or execution performance',
        'research_only':True,'trading_authority':False,'certification_authority':False}


class OfficialEventScoring:
    def __init__(self,store,index,directory,*,clock,can_write,verify=None,replay=None,policy_extension=None):
        self.store,self.index,self.directory,self.clock,self.can_write=store,index,Path(directory),clock,can_write
        self.verify,self.replay=verify,replay;self.next_check=None;self.attempts={};self.report=None;self.error=None;self.replay_state='pending'
        sources=Path(__file__).parent
        policy={'version':'official-event-research-v30','code_sha256':digest([(sources/n).read_text() for n in ('scoring.py','outcomes.py')]+[(sources.parent/'phase26'/'outcomes.py').read_text()]),
            'target':'official completed NHL game, conditional on completion; not native token payout',
            'selection':'earliest timestamp then forecastID per official game/model; all losses retained',
            'cadence_seconds':300,'checks_per_cycle':16,'current_inventory_budget':2048,
            'market_comparison':'withheld for conditional/noncomparable forecasts','certification':'native payout gates remain unchanged; no promotion'}
        if policy_extension is not None:policy['extension']=policy_extension
        self.enrollment_id=digest(['official-event-research-v30',policy])
        prior=store.get(self.enrollment_id)
        if prior is None:
            if not can_write():raise ValueError('official_event_enrollment_archive_backpressure')
            now=at(clock());store.append(EventScoringEnrollment(id=self.enrollment_id,timestamp=now,available_at=now,source='neraium-poly/official-event-research/v30',policy=policy))
        elif _body(prior).get('policy')!=policy:raise ValueError('official_event_enrollment_policy_binding_mismatch')
        rows=latest(store,'EventScoreSnapshot',limit=1)
        if rows and rows[0]['enrollment_id']==self.enrollment_id:self.report=rows[0]['report'];self.replay_state='cached_until_source_replay'

    def supports(self,ref):
        f=ref['forecast']
        return f.get('domain')=='sports' and ref.get('review',{}).get('descriptor',{}).get('league')=='NHL'

    def evaluate_labels(self,labels):
        return evaluation(labels)

    async def step(self):
        now=at(self.clock())
        if self.next_check is not None and now<self.next_check or not self.can_write():return False
        if self.index.report(as_of=now).get('projection',{}).get('status')!='caught_up':return False
        if self.verify is None:
            from .outcomes import replay_official_event, verify_official_event
            self.verify,self.replay=verify_official_event,replay_official_event
        entries,anchor=self.index.snapshot()
        if anchor is None or at(anchor['available_at'])>now:raise ValueError('event_scoring_causal_source_anchor_required')
        refs={r['forecast_id']:r for r in entries if r.get('type')=='forecast' and r.get('replay_verified')}
        if len(refs)>2048:raise ValueError('event_scoring_forecast_inventory_budget_exceeded')
        due=[];labels=[];reasons=Counter();seen_groups=set();checked=0
        for ref in refs.values():
            f=ref['forecast'];identity=digest(['official-event-label-v30',self.enrollment_id,f['id'],ref['forecast_sha256'],ref['source_study_sha256']])
            existing=self.store.get(identity)
            if existing is not None:
                label=_body(existing)
                if (label['original_forecast_sha256']!=ref['forecast_sha256'] or label['original_study_sha256']!=ref['source_study_sha256']
                    or label['native_payout_verified'] is not False):raise ValueError('official_event_recovery_source_binding_mismatch')
                try:
                    study=_body(await _thread(self.store.get,ref['source_id']))
                    if digest(study)!=ref['source_study_sha256']:raise ValueError('official_event_recovered_source_hash_mismatch')
                    full=next(x for x in study['forecasts'] if x['id']==f['id'])
                    proof=await _thread(self.replay,label['result'],study,full,evidence_root=self.directory,as_of=now)
                    if digest(proof)!=digest(label['replay']):raise ValueError('official_event_recovered_proof_mismatch')
                    labels.append({'label_id':identity,'forecast':_scoring_forecast(full),'forecast_available_at':study['available_at'],'proof':proof})
                except (ValueError,KeyError,TypeError,OSError,StopIteration) as e:reasons[str(e)[:160]]+=1
                continue
            if at(f['event_end_time'])>now:reasons['event_not_yet_mature']+=1;continue
            if not self.supports(ref):reasons['official_event_adapter_unavailable_for_domain_or_league']+=1;continue
            if f.get('domain')=='sports' and now<at(f['event_end_time'])+timedelta(hours=1):reasons['sports_start_is_not_verified_completion']+=1;continue
            if f['id'] in self.attempts and now-self.attempts[f['id']]<timedelta(seconds=300):continue
            due.append((ref,identity))
        # Different native events first; repeat model labels never grow event n.
        due.sort(key=lambda x:(at(x[0]['forecast']['event_end_time']),x[0]['forecast_id']))
        first=[];rest=[]
        for pair in due:
            group=pair[0]['forecast']['event_id']
            (rest if group in seen_groups else first).append(pair);seen_groups.add(group)
        for ref,identity in (first+rest)[:16]:
            if not self.can_write():break
            f=ref['forecast'];self.attempts[f['id']]=now;checked+=1
            try:
                study=_body(await _thread(self.store.get,ref['source_id']))
                if digest(study)!=ref['source_study_sha256'] or _payload_bytes(study,32*1024**2)>32*1024**2:
                    raise ValueError('official_event_original_study_integrity_or_size')
                original=next(x for x in study['forecasts'] if x['id']==f['id'])
                if digest(original)!=ref['forecast_sha256']:raise ValueError('official_event_original_forecast_integrity')
                result=await self.verify(original,directory=self.directory,clock=self.clock)
                if result.get('event_result_verified') is not True:
                    reasons[str(result.get('reason',result.get('reasons','official_result_not_final')))[:160]]+=1;continue
                proof=await _thread(self.replay,result,study,original,evidence_root=self.directory,as_of=at(self.clock()))
                if (proof.get('event_result_verified') is not True or proof.get('native_payout_verified') is not False
                    or proof.get('trading_authority') is not False or proof.get('certification_authority') is not False):
                    raise ValueError('official_event_independent_replay_failed')
                completed=at(self.clock())
                row=OfficialEventLabelStudy(id=identity,timestamp=completed,available_at=completed,source='neraium-poly/official-event-research/v30',
                    enrollment_id=self.enrollment_id,original_study_id=study['id'],original_study_sha256=digest(study),
                    original_forecast_sha256=digest(original),forecast_id=f['id'],source_anchor=anchor,result=result,replay=proof)
                if not self.can_write():raise ValueError('official_event_evidence_archive_backpressure')
                self.store.append(row);labels.append({'label_id':identity,'forecast':_scoring_forecast(original),'forecast_available_at':study['available_at'],'proof':proof})
            except (ValueError,KeyError,TypeError,OSError,StopIteration) as e:reasons[str(e)[:160]]+=1
        self.attempts={k:v for k,v in self.attempts.items() if k in refs}
        completed=at(self.clock());report=self.evaluate_labels(labels)
        report.update(as_of=completed.isoformat(),inventory_forecasts=len(refs),checks_this_cycle=checked,collection_rejections=dict(reasons),
            source_anchor_id=anchor['id'],next_check_seconds=300)
        if not self.can_write():raise ValueError('official_event_score_archive_backpressure')
        self.store.append(EventScoreSnapshot(id=digest(['official-event-score',self.enrollment_id,completed.isoformat()]),
            timestamp=completed,available_at=completed,source='neraium-poly/official-event-research/v30',enrollment_id=self.enrollment_id,source_anchor=anchor,report=report))
        self.report=report;self.next_check=completed+timedelta(seconds=300);self.error=None;self.replay_state='independently_replayed'
        return True

    def status(self):
        return {**(self.report or {'status':'pending'}),'runtime_error':self.error,'replay_state':self.replay_state,'native_payout_verified':False,'research_only':True,'trading_authority':False,'certification_authority':False}
