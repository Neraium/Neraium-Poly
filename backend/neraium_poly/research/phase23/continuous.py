"""Bounded prospective challengers in the existing archive, with no order API."""
import asyncio
import hashlib
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.finance import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase18.sources import at
from neraium_poly.research.phase23.models import (
    SPORTS_MODELS,
    enrollment_definitions,
    forecast_models,
    forecast_nfl,
    map_challenger_contract,
)
from neraium_poly.research.phase23.sources import collect_challenger_evidence, load_existing_sports
from pydantic import Field


class ChallengerStudy(Record):
    operation: Literal['enrollment','forecast_batch','scan']
    enrollment_id: str
    enrollment: list[dict] = Field(default_factory=list)
    source_frame_id: str | None = None
    source_frame_sha256: str | None = None
    forecasts: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    observations: list[dict] = Field(default_factory=list)
    rejections: dict = Field(default_factory=dict)
    checkpoint: dict
    checkpoint_sha256: str
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


def horizon_bucket(seconds):
    return next(label for bound,label in [(7200,'0-2h'),(28800,'2-8h'),(86400,'8-24h'),(259201,'24-72h')] if seconds <= bound)


class ChallengerResearch:
    """Two source groups in parallel per300s; sixteen contracts and32forecasts max.

    Durable dedup spans model/parent/market/token/horizon, never source receipt IDs.
    Source lineages remain explicit: two models do not create two independent
    events or sources. Missing or stale execution books reject research enrollment.
    """
    def __init__(self, store, *, clock=None, can_write=None, collector=None, interval=300, sports_directory=None):
        if not 300 <= interval <= 3600:
            raise ValueError('bounded_challenger_interval_required')
        self.store, self.clock = store, clock or (lambda: datetime.now(UTC))
        self.can_write, self.collector = can_write or (lambda: True), collector or collect_challenger_evidence
        self.interval, self.lock, self.last_error = interval, asyncio.Lock(), None
        self.definitions = enrollment_definitions()
        directory=getattr(store,'directory',None)
        self.sports_directory=Path(sports_directory) if sports_directory else Path(directory)/'event-intelligence/sports/sources' if directory else None
        self.code_sha256 = hashlib.sha256(b''.join(Path(__file__).with_name(n).read_bytes() for n in ('models.py','sources.py','continuous.py'))).hexdigest()
        self.enrollment_id = digest(['phase23-prospective-research', self.definitions, self.code_sha256])
        self.state = {'version':'phase23-challengers-v1','enrollment_id':self.enrollment_id,'code_sha256':self.code_sha256,
            'enrolled':False,'last_at':None,'last_attempt_at':None,'scans':0,'forecasts':0,
            'parents':[],'seen':[],'source_group_attempts':{},'rejections':{},'models':{d['model_id']:{'forecasts':0,'resolved':0,'brier':None,'log_loss':None} for d in self.definitions},'latest':[]}
        rows = store.latest('ChallengerStudy', limit=2)
        if rows:
            row = max((ChallengerStudy.model_validate(r) for r in rows), key=lambda r: unpack_checkpoint(r.checkpoint)['scans']); saved = unpack_checkpoint(row.checkpoint)
            if digest(saved) != row.checkpoint_sha256 or saved.get('enrollment_id') != self.enrollment_id or saved.get('code_sha256') != self.code_sha256:
                raise ValueError('challenger_recovery_or_immutable_enrollment_mismatch')
            self.state = saved

    def _commit(self, state, *, operation, timestamp, **fields):
        state['last_at'] = timestamp.isoformat()
        packed = pack_checkpoint(state)
        row = ChallengerStudy(id=digest([self.enrollment_id, operation, state['scans'], timestamp.isoformat(),fields]),
            timestamp=timestamp, available_at=timestamp, source='neraium-poly/research/challengers/v23',
            operation=operation, enrollment_id=self.enrollment_id,
            enrollment=self.definitions if operation=='enrollment' else [],
            checkpoint=packed, checkpoint_sha256=digest(state), **fields)
        if not self.can_write():
            raise ValueError('challenger_archive_budget_withheld')
        self.store.append(row)
        self.state = state
        return row

    async def step(self, frame):
        if self.lock.locked() or not self.can_write():
            return False
        async with self.lock:
            now = at(self.clock())
            if self.state['last_attempt_at'] and (now-at(self.state['last_attempt_at'])).total_seconds() < self.interval:
                return False
            if not self.state['enrolled']:
                state = deepcopy(self.state);state['enrolled']=True
                self._commit(state, operation='enrollment', timestamp=now)
            raw = frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
            if not isinstance(raw,dict) or not isinstance(raw.get('markets'),list) or not isinstance(raw.get('books'),list) or len(raw['markets'])>4000 or len(raw['books'])>4000:
                raise ValueError('bounded_challenger_frame_required')
            if raw.get('available_at') and at(raw['available_at']) > now:
                raise ValueError('future_challenger_frame')
            bytoken, duplicates = {}, set()
            for b in raw['books']:
                b = OrderBookSnapshot.model_validate(b)
                if b.token_id in bytoken:duplicates.add(b.token_id)
                bytoken[b.token_id] = b
            state = deepcopy(self.state);state['last_attempt_at']=now.isoformat();state['scans']+=1
            reasons, groups, seen = Counter(), defaultdict(list), set(state['seen'])
            sports_candidates={}
            for value in raw['markets']:
                m = MarketSnapshot.model_validate(value)
                if m.resolution_source.rstrip('/')=='https://www.nfl.com/scores' and ' vs. ' in m.question:
                    b=bytoken.get(m.token_id)
                    if (b and b.token_id not in duplicates and b.market_id==m.market_id and b.exchange==m.exchange and b.source in PUBLIC_BOOK_SOURCES
                        and assess_book(b,now,max_spread=.05,expected_token=m.token_id).healthy
                        and min(sum(x.price*x.size*.25 for x in b.bids[:3]),sum(x.price*x.size*.25 for x in b.asks[:3]))>=2):
                        sports_candidates.setdefault(m.market_id,(m,b))
                    else:reasons['nfl_fresh_two_sided_depth_required']+=1
                if m.outcome != 'Yes':
                    continue # One outcome per contract avoids token count inflation.
                c = map_challenger_contract(m,now=now)
                if not c.compatible or c.review_required:
                    reasons.update(c.reasons or ['exact_supported_research_contract_required']);continue
                b = bytoken.get(m.token_id)
                if b is None or b.token_id in duplicates or b.market_id!=m.market_id or b.exchange!=m.exchange or b.source not in PUBLIC_BOOK_SOURCES:
                    reasons['native_unique_book_identity_required']+=1;continue
                quality = assess_book(b,now,max_spread=.05,expected_token=m.token_id)
                if not quality.healthy:
                    reasons.update(quality.reasons);continue
                if min(sum(x.price*x.size*.25 for x in b.bids[:3]),sum(x.price*x.size*.25 for x in b.asks[:3]))<2:
                    reasons['two_sided_depth_below_standard_notional']+=1;continue
                bucket = horizon_bucket((m.end_time-now).total_seconds())
                keys = {d['model_id']:digest([self.enrollment_id,d['model_id'],m.event_id,m.market_id,m.token_id,bucket]) for d in self.definitions[:2]}
                if all(k in seen for k in keys.values()):
                    reasons['existing_prospective_model_contract_horizon']+=1;continue
                groups[(c.parameters['symbol'],c.parameters['period_start_utc'])].append((m,b,c,keys,bucket))
            # Distinct parent windows before additional thresholds; no future labels.
            chosen = sorted(groups, key=lambda key:(state['source_group_attempts'].get('|'.join(key),0),at(key[1]),key))[:2]
            for key in chosen:
                group_id='|'.join(key)
                state['source_group_attempts'][group_id]=state['source_group_attempts'].get(group_id,0)+1
            async def acquire(key):
                try:return key,await self.collector(groups[key][0][2],now=now),None
                except Exception as error:  # noqa: BLE001 - acquisition failure withholds research only
                    return key,(),f'{type(error).__name__}:{str(error)[:120]}'
            acquired = await asyncio.gather(*(acquire(key) for key in chosen))
            forecasts, evidence_rows, observations = [], [], []
            count = 0
            for key,evidence,error in acquired:
                if error:
                    reasons['external_source_withheld:'+error]+=1;continue
                evidence_rows.extend(x.model_dump(mode='json') if hasattr(x,'model_dump') else x for x in evidence)
                for m,b,c,keys,bucket in sorted(groups[key], key=lambda x:(x[0].event_id,x[0].market_id))[:8]:
                    cutoff = at(self.clock())
                    try:
                        if not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy:
                            reasons['book_stale_after_external_retrieval']+=1;continue
                        results = await asyncio.to_thread(forecast_models,c,evidence,cutoff=cutoff)
                        created = at(self.clock())
                        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:
                            reasons['book_stale_after_model_computation']+=1;continue
                        for result in results:
                            if keys[result['model_id']] in seen:continue
                            if len(seen)>=8192:
                                reasons['durable_enrollment_capacity_reached']+=1;continue
                            forecast = {**result,'id':keys[result['model_id']],'timestamp':created.isoformat(),
                                'enrollment_id':self.enrollment_id,'market_probability':(b.bids[0].price+b.asks[0].price)/2,
                                'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'book':b.model_dump(mode='json'),
                                'market':m.model_dump(mode='json'),'contract':c.model_dump(mode='json'),
                                'horizon_bucket':bucket,'independence_reviewed':False,'reviewed_dependency_group':None,
                                'baseline_scope':'same preforecast observed two-sided quote; not an independent predictive feature'}
                            forecasts.append(forecast);seen.add(forecast['id']);state['seen'].append(forecast['id']);state['forecasts']+=1
                            state['models'][result['model_id']]['forecasts']+=1
                            if m.event_id not in state['parents']:state['parents'].append(m.event_id)
                        observations.append({'market_id':m.market_id,'event_id':m.event_id,'token_id':m.token_id,'cutoff':cutoff.isoformat(),
                            'probabilities':{r['model_id']:r['probability'] for r in results},
                            'disagreement':abs(results[0]['probability']-results[1]['probability']),
                            'source_lineages_shared':True,'source_count':1,'independent_corroboration':False})
                        count+=1
                    except (ValueError,TypeError,KeyError,OverflowError) as error:
                        reasons[str(error)[:160]]+=1
            if sports_candidates and self.sports_directory:
                try:
                    data,reference=await asyncio.to_thread(load_existing_sports,self.sports_directory,cutoff=at(self.clock()))
                    for m,b in list(sports_candidates.values())[:8]:
                        cutoff=at(self.clock())
                        if (m.end_time is None or not 0<(m.end_time-cutoff).total_seconds()<=72*3600
                            or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy):
                            reasons['nfl_causal_near_term_book_required']+=1;continue
                        bucket=horizon_bucket((m.end_time-cutoff).total_seconds())
                        keys={name:digest([self.enrollment_id,name,m.event_id,m.market_id,m.token_id,bucket]) for name in SPORTS_MODELS}
                        if all(k in seen for k in keys.values()):
                            reasons['existing_nfl_model_contract_horizon']+=1;continue
                        try:results=await asyncio.to_thread(forecast_nfl,m,data,cutoff=cutoff)
                        except (ValueError,TypeError,KeyError) as error:
                            reasons['nfl_model_withheld:'+str(error)[:120]]+=1;continue
                        created=at(self.clock())
                        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:
                            reasons['nfl_book_stale_after_model']+=1;continue
                        for result in results:
                            fid=keys[result['model_id']]
                            if fid in seen:continue
                            if len(seen)>=8192:
                                reasons['durable_enrollment_capacity_reached']+=1;continue
                            f={**result,'id':fid,'timestamp':created.isoformat(),'enrollment_id':self.enrollment_id,
                                'market_probability':None,'market_expected_payout':(b.bids[0].price+b.asks[0].price)/2,
                                'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'book':b.model_dump(mode='json'),
                                'market':m.model_dump(mode='json'),'source_reference':reference,
                                'evidence_ids':[reference['manifest_sha256']],'horizon_bucket':bucket,
                                'independence_reviewed':False,'reviewed_dependency_group':None,
                                'baseline_scope':'Observed quote is expected payout under half-payoff ties, never a binary win probability'}
                            forecasts.append(f);seen.add(fid);state['seen'].append(fid);state['forecasts']+=1
                            state['models'][result['model_id']]['forecasts']+=1
                            if m.event_id not in state['parents']:state['parents'].append(m.event_id)
                        count+=1
                except (ValueError,OSError,TypeError,KeyError) as error:
                    reasons['nfl_source_withheld:'+str(error)[:120]]+=1
            ended=at(self.clock());state['latest']=[{k:f[k] for k in ['id','model_id','event_id','market_id','probability','market_probability','timestamp','calibration_status']} for f in forecasts][-32:]
            total=Counter(state['rejections']);total.update(reasons);state['rejections']=dict(total)
            self._commit(state,operation='forecast_batch' if forecasts else 'scan',timestamp=ended,
                source_frame_id=raw.get('id'),source_frame_sha256=digest(raw),forecasts=forecasts,
                evidence=evidence_rows,observations=observations,rejections=dict(reasons))
            self.last_error=None
            return bool(count)

    def status(self):
        state=deepcopy(self.state)
        return {'status':'research_only','enrollment_id':self.enrollment_id,'enrollment':self.definitions,
            'last_evaluation_at':state['last_at'],'scans':state['scans'],'forecasts':state['forecasts'],
            'pending_forecasts':state['forecasts'],'unreviewed_parent_events':len(state['parents']),
            'models':state['models'],'latest':state['latest'],'rejections':state['rejections'],
            'resolved_events':0,'qualified_training_events':0,'qualified_heldout_events':0,
            'calibration_status':'independently_verified_event_disjoint_outcomes_required',
            'source_groups_per_cycle':2,'source_parallelism':2,'interval_seconds':self.interval,
            'dedup_scope':'immutable model/parent/contract/token/horizon; same parents are not independent samples',
            'last_error':self.last_error,'research_only':True,'trading_authority':False,
            'certification_authority':False,'live_trading_enabled':False}
