"""Frozen prospective comparisons, conservative date blocks and causal baselines.

Parent IDs and operational blocks never certify statistical independence. No
outcome, positive payout or profitable trade is required for enrollment.
"""
import hashlib
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at, canonical_event

POLICY={'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'version':'phase46-v1','max_trials':512,'max_enrollments_per_tick':4,'baselines':['external','market','zero','one','neutral','past_frequency','past_horizon_frequency'],
        'selection':'unresolved source-backed events; new dependency blocks, entropy, near-term depth; no label selection',
        'independence':'canonical source events and conservative domain/date blocks are not certification; review required',
        'training':'earliest forecast per historical block selected from ALL forecasts, then require its native result available before decision; exclude target block; Jeffreys prior; no future labels',
        'promotion':'none; unchanged certified100 training/100 heldout gates'}


class ResearchRecord46(Record):
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


class ProgramDeclaration46(ResearchRecord46):
    policy:dict


class ProspectiveEvent46(ResearchRecord46):
    declaration_id:str
    source_forecast:dict
    source_binding:dict
    canonical_event:str
    dependency_block:str
    horizon:str
    book:dict
    probabilities:dict
    training:dict


class ProspectiveResult46(ResearchRecord46):
    trial_id:str
    proof:dict


def identity(f):
    descriptor,event,_tags=canonical_event(f)
    domain=f['domain'];day=at(f['event_end_time']).date().isoformat()
    # Shared crypto date absorbs cross-asset/threshold dependence; weather
    # stations share a day too. Different days can STILL be correlated.
    block=digest([domain,day]) if domain in ('crypto','weather','finance') else event
    return event,block,descriptor


def horizon(f,now):
    hours=(at(f['event_end_time'])-at(now)).total_seconds()/3600
    return '0-6h' if hours<=6 else '6-24h' if hours<=24 else '1-3d' if hours<=72 else 'longer'


def frequency(f,forecasts,labels,now):
    _event,target,_=identity(f);representatives={}
    for old in forecasts.values():
        try:_e,block,_d=identity(old)
        except (ValueError,KeyError,TypeError):continue
        if old['domain']!=f['domain'] or block==target:continue
        rank=(at(old['timestamp']),old['market_id'],old['token_id'],old['id'])
        if block not in representatives or rank<representatives[block][0]:representatives[block]=(rank,old)
    ys=[];hs=[];ids=[]
    for _rank,old in representatives.values():
        p=labels.get(old['id'])
        if not p or p.get('native_payout_verified') is not True or p.get('payout') not in (0,1):continue
        if any(p.get(k)!=old[k] for k in ('market_id','event_id','token_id','rules_sha256')):continue
        if not at(old['timestamp'])<at(p['resolved_at'])<=at(p['available_at'])<=at(now):continue
        ys.append(p['payout']);ids.append(old['id'])
        if horizon(old,old['timestamp'])==horizon(f,now):hs.append(p['payout'])
    return (sum(ys)+.5)/(len(ys)+1),(sum(hs)+.5)/(len(hs)+1),{'blocks':len(ys),'horizon_blocks':len(hs),'forecast_ids':ids,'cutoff':at(now).isoformat(),'fitted_calibration':False,'prior':'Jeffreys beta(.5,.5); baseline only'}


class Program:
    def __init__(self,store,clock,can_write):
        self.store,self.clock,self.can_write=store,clock,can_write
        old=store.latest('ProgramDeclaration46',1)
        if old:
            self.declaration=old[0]
            if self.declaration['policy']!=POLICY:raise ValueError('frozen Phase46 program policy changed')
        else:
            now=at(clock());r=ProgramDeclaration46(id=digest(['program46',POLICY]),timestamp=now,available_at=now,source='neraium-poly/prospective-program/v46',policy=POLICY)
            if not can_write():raise ValueError('program capacity withheld')
            store.append(r);self.declaration=r.model_dump(mode='json')
        self.rows={r['id']:r for r in store.latest('ProspectiveEvent46',512)}
        self.results={r['trial_id']:r for r in store.latest('ProspectiveResult46',512)}
        self.withheld=Counter()
    def register(self,current,refs,frame,history,labels):
        now=at(self.clock());markets={m.token_id:m for m in frame.markets};books={b.token_id:b for b in frame.books};options=[]
        seen={r['dependency_block'] for r in self.rows.values()}
        for f in sorted(current.values(),key=lambda v:at(v['timestamp']),reverse=True):
            try:
                if not at(self.declaration['timestamp'])<=at(f['timestamp'])<=now<at(f['event_end_time']) or (now-at(f['timestamp'])).total_seconds()>300:continue
                event,block,_=identity(f);key=digest(['trial46',f['model_id'],event,f['market_id'],f['token_id']])
                if key in self.rows:continue
                m=markets[f['token_id']];b=books[f['token_id']];ref=refs[f['id']]
                if ref['forecast_sha256']!=digest(f):raise ValueError('original_model_replay_binding_mismatch')
                if b.source not in PUBLIC_BOOK_SOURCES or b.market_id!=m.market_id or not assess_book(b,now,max_age_seconds=15,max_spread=.15,expected_token=m.token_id).healthy:raise ValueError('fresh_executable_book_required')
                if any(f['market'].get(k)!=getattr(m,k) for k in ('market_id','event_id','token_id','question','outcome','resolution_rules','resolution_source')):raise ValueError('exact_contract_required')
                mid=(b.bids[0].price+b.asks[0].price)/2;hours=(at(f['event_end_time'])-now).total_seconds()/3600
                options.append(((block in seen,abs(mid-.5),hours,key),key,f,ref,event,block,b,mid))
            except (KeyError,TypeError,ValueError) as error:self.withheld[str(error)[:100]]+=1
        for written,(_rank,key,f,ref,event,block,b,mid) in enumerate(sorted(options,key=lambda v:v[0])):
            if written>=4 or len(self.rows)>=512:break
            if key in self.rows:continue
            freq,timefreq,training=frequency(f,history,labels,now)
            row=ProspectiveEvent46(id=key,timestamp=now,available_at=now,source='neraium-poly/prospective-program/v46',declaration_id=self.declaration['id'],
                source_forecast=f,source_binding=ref,canonical_event=event,dependency_block=block,horizon=horizon(f,now),book=b.model_copy(update={'bids':b.bids[:8],'asks':b.asks[:8]}).model_dump(mode='json'),
                probabilities={'external':f['probability'],'market':mid,'zero':0.,'one':1.,'neutral':.5,'past_frequency':freq,'past_horizon_frequency':timefreq},training=training)
            if not self.can_write():raise ValueError('prospective enrollment capacity withheld')
            self.store.append(row);self.rows[key]=row.model_dump(mode='json')
    def due(self):
        now=at(self.clock())
        return {r['source_forecast']['id']:{'forecast':r['source_forecast'],'study_id':r['source_binding']['study_id'],'study_sha256':r['source_binding']['study_sha256']} for key,r in self.rows.items() if key not in self.results and at(r['source_forecast']['event_end_time'])<=now}
    def settle(self,proofs):
        now=at(self.clock())
        for key,r in self.rows.items():
            f=r['source_forecast'];p=proofs.get(f['id'])
            if key in self.results or p is None:continue
            if (p.get('verified') is not True or p.get('native_payout_verified') is not True or type(p.get('payout')) not in (int,float) or p['payout'] not in (0,1)
                or p.get('forecast_id')!=f['id'] or any(p.get(k)!=f[k] for k in ('market_id','event_id','token_id','rules_sha256'))
                or not at(f['timestamp'])<=at(r['timestamp'])<at(p['resolved_at'])<=at(p['available_at'])<=now):raise ValueError('exact prospective native proof required')
            row=ProspectiveResult46(id=digest(['result46',key,p]),timestamp=now,available_at=now,source='neraium-poly/native-program-result/v46',trial_id=key,proof=p)
            if not self.can_write():raise ValueError('result capacity withheld')
            self.store.append(row);self.results[key]=row.model_dump(mode='json')
    def report(self):
        blocks=defaultdict(list);payouts=Counter()
        for key,result in self.results.items():
            r=self.rows[key];y=result['proof']['payout'];blocks[r['dependency_block']].append((r,y));payouts[str(y)]+=1
        scores={}
        if blocks:
            for name in POLICY['baselines']:
                bs=[];logs=[]
                for values in blocks.values():
                    bs.append(sum((r['probabilities'][name]-y)**2 for r,y in values)/len(values))
                    logs.append(-sum(y*math.log(max(1e-12,r['probabilities'][name]))+(1-y)*math.log(max(1e-12,1-r['probabilities'][name])) for r,y in values)/len(values))
                scores[name]={'brier':sum(bs)/len(bs),'log_loss_clipped_1e_minus12':sum(logs)/len(logs)}
        by_model={}
        for model in {r['source_forecast']['model_id'] for r in self.rows.values()}:
            own={block:[(r,y) for r,y in values if r['source_forecast']['model_id']==model] for block,values in blocks.items()}
            own={k:v for k,v in own.items() if v}
            by_model[model]={'resolved_blocks':len(own),'scores':{name:{'brier':sum(sum((r['probabilities'][name]-y)**2 for r,y in values)/len(values) for values in own.values())/len(own),'log_loss_clipped_1e_minus12':-sum(sum(y*math.log(max(1e-12,r['probabilities'][name]))+(1-y)*math.log(max(1e-12,1-r['probabilities'][name])) for r,y in values)/len(values) for values in own.values())/len(own)} for name in POLICY['baselines']} if own else {}}
        return {'by_model':by_model,'prospective_trials':len(self.rows),'native_results':len(self.results),'positive_zero_payouts':dict(payouts),'conservative_date_blocks':len(blocks),'canonical_source_events':len({r['canonical_event'] for r in self.rows.values()}),'scores_equal_block_weight':scores,
                'reviewed_independent_training':0,'reviewed_independent_heldout':0,'calibration_fit':False,'confidence_interval':None,'withholding':dict(self.withheld),'policy':POLICY,'limitation':'no independence certification; shared dates and latent regimes remain correlated; no winner without independent prospective evidence'}


def inventory(forecasts,labels):
    tokens={};parents=set();events=set();blocks=set();unmapped=0;model_payouts=Counter()
    for fid,p in labels.items():
        f=forecasts[fid]
        if p.get('native_payout_verified') is not True:continue
        tokens[(f['market_id'],f['token_id'])]=p['payout'];parents.add(f['event_id']);model_payouts[str(p['payout'])]+=1
        try:event,block,_=identity(f);events.add(event);blocks.add(block)
        except (ValueError,KeyError,TypeError):unmapped+=1
    return {'model_labels':sum(model_payouts.values()),'outcome_tokens':len(tokens),'native_parent_ids':len(parents),'canonical_source_events':len(events),'conservative_date_blocks':len(blocks),'model_payout_counts':dict(model_payouts),
            'positive_contract_tokens':sum(p==1 for p in tokens.values()),'zero_contract_tokens':sum(p==0 for p in tokens.values()),'unmapped_model_labels':unmapped,'reviewed_independent_samples':0,'limitation':'labels, contracts, native parents and date blocks are distinct; no statistical independence certification'}
