"""Replay challenger forecasts and require native settlement plus final reference data."""

import asyncio
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase18.sources import at, collect_resolution_evidence, completed_minutes
from pydantic import Field


class ChallengerOutcomeStudy(Record):
    operation: Literal['outcome_check', 'resolution_scan'] = 'outcome_check'
    original_study_id: str | None = None
    original_study_sha256: str | None = None
    forecast_id: str | None = None
    outcome: dict | None = None
    evidence: list[dict] = Field(default_factory=list)
    reason: str | None = None
    checkpoint: dict
    checkpoint_sha256: str
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


def replay_forecast(study, forecast, *, as_of):
    from .models import forecast_models, map_challenger_contract

    now = at(as_of)
    if study.get('operation') != 'forecast_batch' or study.get('trading_authority') or study.get('certification_authority'):
        raise ValueError('original research forecast batch required')
    if sum(x.get('id') == forecast['id'] for x in study.get('forecasts', [])) != 1:
        raise ValueError('unique original forecast membership required')
    created, cutoff = at(forecast['timestamp']), at(forecast['evidence_cutoff'])
    if not cutoff <= created <= at(study['available_at']) <= now:
        raise ValueError('prospective forecast temporal integrity required')
    m = MarketSnapshot.model_validate(forecast['market'])
    b = OrderBookSnapshot.model_validate(forecast['book'])
    c = DomainContract.model_validate(forecast['contract'])
    if (b.market_id != m.market_id or b.source not in PUBLIC_BOOK_SOURCES
            or not assess_book(b, created, max_spread=.05, expected_token=m.token_id).healthy
            or digest(b.model_dump(mode='json')) != forecast['book_sha256']
            or any(forecast[k] != getattr(m,k) for k in ('event_id','market_id','token_id'))
            or forecast['rules_sha256'] != c.rules_sha256):
        raise ValueError('original book contract and token identity mismatch')
    rebound = map_challenger_contract(m, now=cutoff)
    if not rebound.compatible or rebound.review_required or rebound.parameters != c.parameters or rebound.rules_sha256 != c.rules_sha256:
        raise ValueError('exact original rules replay required')
    ids = forecast['evidence_ids']
    evidence = [DomainEvidence.model_validate(x) for x in study['evidence'] if x['id'] in ids]
    if len(evidence) != len(ids) or {e.id for e in evidence} != set(ids):
        raise ValueError('original external evidence identity required')
    by_id = {e.id:e for e in evidence}
    evidence = tuple(by_id[x] for x in ids)
    result = next((x for x in forecast_models(c,evidence,cutoff=cutoff) if x['model_id']==forecast['model_id']), None)
    if result is None or any(forecast.get(k) != v for k,v in result.items()):
        raise ValueError('original independent model result replay failed')
    if forecast['market_probability'] != (b.bids[0].price+b.asks[0].price)/2:
        raise ValueError('contemporaneous market baseline mismatch')
    ref = SettlementProofReference(id=forecast['id'], event_id=m.event_id, market_id=m.market_id,
        token_id=m.token_id,timestamp=created,evidence_cutoff=cutoff,
        resolution_rules_sha256=c.rules_sha256,original_record_sha256=digest(forecast))
    return m,c,ref


def verify_outcome(row, study, forecast, *, evidence_root, as_of):
    """No asserted verification flag substitutes for source/model/native proof replay."""
    now = at(as_of)
    record = ChallengerOutcomeStudy.model_validate(row)
    if record.available_at > now or record.outcome is None or record.forecast_id != forecast['id']:
        raise ValueError('available original-bound outcome required')
    if record.original_study_id != study['id'] or record.original_study_sha256 != digest(study):
        raise ValueError('immutable original study binding required')
    m,c,ref = replay_forecast(study,forecast,as_of=now)
    outcome = VerifiedEventOutcome.model_validate(record.outcome)
    if not verify_collected_outcome(outcome,m,ref,Path(evidence_root)):
        raise ValueError('native settlement proof replay failed')
    start,end = map(at,(c.parameters['period_start_utc'],c.parameters['period_end_utc']))
    if not at(forecast['timestamp']) < end <= outcome.settled_at <= record.available_at:
        raise ValueError('completed exact window and native settlement time required')
    if len(record.evidence)!=1:
        raise ValueError('one complete final reference required')
    ev=DomainEvidence.model_validate(record.evidence[0]);p=ev.payload;end_ms=int(end.timestamp()*1000)-1
    if (p.get('window_mode')!='resolution' or p.get('end_ms')!=end_ms
        or ev.timestamp<end or at(p['requested_at'])<end
        or ev.source_timestamp!=datetime.fromtimestamp(end_ms/1000,UTC)):
        raise ValueError('final reference time and window mismatch')
    candles=completed_minutes(ev,cutoff=record.available_at,symbol=c.parameters['symbol'],require_fresh=False)
    window=[x for x in candles if int(start.timestamp()*1000)<=x['open_ms']<=end_ms]
    if (not window or window[0]['open_ms']!=int(start.timestamp()*1000) or window[-1]['close_ms']!=end_ms
        or len(window)!=(end_ms+1-int(start.timestamp()*1000))//60000):
        raise ValueError('complete exact final settlement-day candles required')
    yes=int(min(x['low'] for x in window)<=c.parameters['threshold'])
    payout=yes if c.parameters['selected_outcome']=='Yes' else 1-yes
    if outcome.payout!=payout:
        raise ValueError('native settlement and independent reference disagree')
    p=forecast['probability'];q=forecast['market_probability']
    return {'forecast_id':forecast['id'],'event_id':forecast['event_id'],'model_id':forecast['model_id'],
        'payout':payout,'brier':(p-payout)**2,'market_brier':(q-payout)**2,
        'log_loss':-math.log(p if payout else 1-p) if (p if payout else 1-p)>0 else None,
        'log_loss_status':'finite' if (p if payout else 1-p)>0 else 'positive_infinity',
        'verified':True,'independence_reviewed':False,'trading_authority':False,
        'market_id':forecast['market_id'],'token_id':forecast['token_id'],'rules_sha256':forecast['rules_sha256'],
        'outcome':payout,'resolved_at':outcome.settled_at.isoformat(),'available_at':record.available_at.isoformat(),
        'reviewed_dependency_group':forecast.get('reviewed_dependency_group'),'evidence_sha256':digest(record.evidence)}


class ChallengerOutcomes:
    def __init__(self,store,directory,*,clock=None,can_write=None):
        self.store,self.directory=store,Path(directory)
        self.clock=clock or (lambda:datetime.now(UTC));self.can_write=can_write or (lambda:True)
        self.state={'last_at':None,'checks':0,'verified_ids':[],'checked':{},'last_reason':None,'registered':{},'last_source_id':None,'verified_by_model':{}}
        rows=store.latest('ChallengerOutcomeStudy',limit=1)
        if rows:
            row=ChallengerOutcomeStudy.model_validate(rows[0]);s=unpack_checkpoint(row.checkpoint)
            if digest(s)!=row.checkpoint_sha256 or s['last_at']!=row.available_at.isoformat():
                raise ValueError('challenger outcome checkpoint mismatch')
            self.state=s

    async def step(self):
        now=at(self.clock())
        if not self.can_write() or (self.state['last_at'] and (now-at(self.state['last_at'])).total_seconds()<300):return False
        registered=deepcopy(self.state)
        studies=self.store.latest('ChallengerStudy',limit=256)
        ids={r['id'] for r in studies}
        if registered['last_source_id'] and registered['last_source_id'] not in ids:
            raise ValueError('resolution_source_index_gap_requires_readonly_backfill')
        for study in studies:
            for f in study.get('forecasts',[]):
                if f['id'] in registered['verified_ids']:continue
                if f['id'] not in registered['registered'] and len(registered['registered'])>=8192:
                    raise ValueError('bounded_pending_outcome_index_capacity_reached')
                registered['registered'][f['id']]={'study_id':study['id'], 'event_end_time':f['event_end_time'], 'domain':f['domain']}
        if studies:registered['last_source_id']=studies[0]['id']
        candidates=[]
        for fid,pointer in registered['registered'].items():
            if pointer['domain']!='crypto' or at(pointer['event_end_time'])>now:continue
            raw=self.store.get(pointer['study_id'])
            if raw is None:raise ValueError('registered_forecast_source_missing')
            study=json.loads(raw[1]);f=next(x for x in study['forecasts'] if x['id']==fid)
            candidates.append((study,f))
        if not candidates:
            registered['last_at']=now.isoformat()
            row=ChallengerOutcomeStudy(id=digest(['phase23-resolution-index',registered]), operation='resolution_scan',
                timestamp=now,available_at=now,source='neraium-poly/challenger-outcome/v23',
                checkpoint=pack_checkpoint(registered),checkpoint_sha256=digest(registered))
            if not self.can_write():return False
            self.store.append(row);self.state=registered
            return False
        next_state=registered
        for study,f in sorted(candidates,key=lambda x:self.state['checked'].get(x[1]['id'],''))[:2]:
            s=deepcopy(next_state);s['checks']+=1;s['checked'][f['id']]=now.isoformat();s['checked']=dict(list(s['checked'].items())[-8192:])
            outcome=None;evidence=[];reason=None
            try:
                m,c,ref=await asyncio.to_thread(replay_forecast,study,f,as_of=now)
                location=self.directory/(now.strftime('%Y%m%dT%H%M%S%fZ')+'-'+f['id'][:12])
                proof=await acquire_verified_outcome(ref,m,location,clock=self.clock)
                if proof is None:raise ValueError('native_finalized_settlement_proof_unavailable')
                evidence=list(await collect_resolution_evidence(c,now=at(self.clock())))
                outcome=proof.model_dump(mode='json')
            except Exception as error:  # noqa: BLE001 - unavailable evidence must withhold labels
                reason=f'{type(error).__name__}:{str(error)[:160]}'
            ended=at(self.clock());s['last_at']=ended.isoformat();s['last_reason']=reason
            fields={'id':digest(['phase23-outcome',f['id'],ended.isoformat()]),'timestamp':ended,'available_at':ended,
                'source':'neraium-poly/challenger-outcome/v23','original_study_id':study['id'],'original_study_sha256':digest(study),
                'forecast_id':f['id'],'outcome':outcome,'evidence':[x.model_dump(mode='json') for x in evidence],'reason':reason}
            if outcome:
                probe=ChallengerOutcomeStudy(**fields,checkpoint=pack_checkpoint(s),checkpoint_sha256=digest(s))
                try:
                    await asyncio.to_thread(verify_outcome,probe.model_dump(mode='json'),study,f,evidence_root=self.directory,as_of=ended)
                    s["verified_by_model"][f["model_id"]]=s["verified_by_model"].get(f["model_id"],0)+1
                    s['verified_ids'].append(f['id']);s['registered'].pop(f['id'],None)
                except Exception as error:  # noqa: BLE001 - unavailable evidence must withhold labels
                    fields['outcome']=None;s['last_reason']=fields['reason']=f'{type(error).__name__}:{str(error)[:160]}'
            if not self.can_write():return False
            row=ChallengerOutcomeStudy(**fields,checkpoint=pack_checkpoint(s),checkpoint_sha256=digest(s))
            self.store.append(row);self.state=next_state=s
        return bool(candidates)

    def status(self):
        return {'status':'research_only','last_at':self.state['last_at'],'checks':self.state['checks'],
            'verified_forecasts':len(self.state['verified_ids']),'registered_pending_forecasts':len(self.state['registered']),'verified_by_model':dict(self.state['verified_by_model']),'last_reason':self.state['last_reason'],
            'verification':'exact model replay plus finalized native proof plus complete independent reference',
            'sports_status':'existing verified NFL outcome pipeline preserved; new ternary challenger scoring requires target-compatible corroboration',
            'trading_authority':False,'certification_authority':False}
