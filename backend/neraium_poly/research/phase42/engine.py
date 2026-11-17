"""Crash-safe alternative shadow portfolios; cannot access any real account/broker.

A fill is a declared execution-model result from a subsequent native book, never
an exchange acknowledgement. All exits use bid depth, never favorable midpoints.
"""
import copy
import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase41.simulation import ProfileExperiment, number
from neraium_poly.research.phase42.strategies import DEFINITIONS, propose

LEGACY_SOURCE_SHA256='34de68d0a56fe84a39c6476299d432f652c3cb9bfb7e4bf934ba7f07318e6734'  # Reviewed Phase42 entry/exit policy; forward-only inventory/provenance transition.
LEGACY_DEFINITIONS_SHA256='d60142b125c6bacb56ed548603a6307402f9b01e308691a0c75f696521c86d94'
DEPLOYED_SOURCE_SHA256='7208eb2e84d64f141fa16e247ec6b92eb30356a6dac2223f5123702035485808'
DEPLOYED_DEFINITIONS_SHA256='2e451f687dec791505d5206c5f9e511ee83342afea9a63da6473c1e799dd070c'
PHASE43_SOURCE_SHA256='c13cda0c3ff41bcf82528c0c569b7766b4d8f11c92dafc00071b53bea635b1cf'
EPS=1e-8
PROFILES={
 'aggressive':{'size':3.,'edge':0.,'spread':.20,'haircut':0.,'unknown_fee':.10},
 'balanced':{'size':5.,'edge':.005,'spread':.10,'haircut':.25,'unknown_fee':None},
 'conservative':{'size':5.,'edge':.03,'spread':.05,'haircut':1.,'unknown_fee':None},
}


class StrategyCycle(Record):
    policy:dict
    previous_id:str|None=None
    previous_sha256:str|None=None
    checkpoint:dict
    state_sha256:str
    events:list
    observations:dict
    trading_authority:Literal[False]=False
    research_only:Literal[True]=True


class StrategyEngine:
    entry_enrollment_open=True
    record_type=StrategyCycle
    identity_prefix='strategy42'
    source_name='neraium-poly/strategy-competition/v42'
    definitions=DEFINITIONS
    profile_configs=PROFILES
    proposer=staticmethod(propose)

    def extra_policy(self):
        root=Path(__file__).parent.parent/'phase44'
        return {'entry_enrollment_open':self.entry_enrollment_open,'research_native_verifier_sha256':{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('native.py','outcomes.py')}}
    _cost=ProfileExperiment._cost
    _size=ProfileExperiment._size
    def __init__(self,store,*,risk_limits,clock,can_write):
        self.store,self.clock,self.can_write=store,clock,can_write;self.risk=dict(risk_limits)
        caps={'aggregate_fraction':.2,'market_fraction':.05,'event_fraction':.1,'correlation_fraction':.1,'daily_loss_fraction':.05,'drawdown_fraction':.1}
        if self.risk['bankroll']!=500 or any(not number(self.risk[k],0,v) for k,v in caps.items()):raise ValueError('approved unchanged risk ceilings required')
        self.policy={'version':'phase42-v1','profiles':self.profile_configs,'strategies':self.definitions,'risk':self.risk,
            'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'definitions_sha256':hashlib.sha256(Path(__file__).with_name('strategies.py').read_bytes()).hexdigest(),
            'extra_slippage_per_share':.0015,'redemption_reserve_per_share':.0005,'latency_seconds':.5,'depth_levels_per_side':8,'participation':min(.1,self.risk['max_liquidity_participation']),
            'economic_sources_sha256':{n:hashlib.sha256((Path(__file__).parent.parent/'phase43'/n).read_bytes()).hexdigest() for n in ('economics.py','tournament.py','baseline.json')},
            'capital':'three mutually exclusive500USD hypothetical portfolios; strategies SHARE each profile capital',
            'fill_assumption':'first eight authentic levels per side only, never extrapolated; later native snapshot with marketable depth; observed growth-only replenishment; passive entries require crossed limit; no guaranteed actual execution',
            'retirement':'after20closed independent-event research observations and negative total net P/L, no new entries; never certify; fixed checkpoint, no holdout reuse',
            'promotion':'no automatic winner; independent held-out verification required'}
        self.policy.update(self.extra_policy())
        self.last=None;self.state={'sequence':0,'last_at':None,'markets_seen':[],'history':{},'prior_forecasts':{},'forecasts':{},'labels':{},
            'profiles':{n:{'cash':500.,'orders':{},'positions':{},'credits':{},'books':{},'seen':[],'closed':[],
                'counts':{},'rejects':{},'peak':500.,'drawdown':0.,'suspended':False,'unrealized':None,'day':None,'day_loss':0.} for n in self.profile_configs}}
        previous=store.latest(self.record_type.__name__,1)
        if previous:self._adopt(previous[0])
    def _adopt(self,row):
        if row['policy']!=self.policy:
            compatible={**row['policy'],'code_sha256':self.policy['code_sha256'],'definitions_sha256':self.policy['definitions_sha256'],'economic_sources_sha256':self.policy['economic_sources_sha256'],**self.extra_policy()}
            closing_only=(row['policy'].get('entry_enrollment_open') is True and self.policy.get('entry_enrollment_open') is False and {**row['policy'],'entry_enrollment_open':False}==self.policy)
            if not closing_only and ((row['policy']['code_sha256'],row['policy']['definitions_sha256']) not in ((LEGACY_SOURCE_SHA256,LEGACY_DEFINITIONS_SHA256),(DEPLOYED_SOURCE_SHA256,DEPLOYED_DEFINITIONS_SHA256),(PHASE43_SOURCE_SHA256,DEPLOYED_DEFINITIONS_SHA256)) or compatible!=self.policy):raise ValueError('frozen strategy source/policy mismatch; no reset permitted')
        state=unpack_checkpoint(row['checkpoint'])
        if digest(state)!=row['state_sha256']:raise ValueError('strategy checkpoint integrity failure')
        if row['previous_id']:
            prior=self.store.get(row['previous_id'])
            if not prior or digest(json.loads(prior[1]))!=row['previous_sha256']:raise ValueError('strategy lineage failure')
        if row['policy']['code_sha256']==DEPLOYED_SOURCE_SHA256 and 'loss_ledger' not in state:
            baseline=json.loads((Path(__file__).parent.parent/'phase43/baseline.json').read_text())
            if baseline['original_cycle']['id']!=row['id'] or baseline['original_cycle']['sha256']!=digest(row):raise ValueError('Phase43 loss baseline does not bind current original cycle; re-audit required')
            state['loss_ledger']=baseline['ledger']
            state['loss_baseline_source']=baseline['original_cycle']
        self.state,self.last=state,row
    def _commit(self,state,events,observations):
        identity=f'{self.identity_prefix}:{self.state["sequence"]+1:012d}'
        prior=self.store.get(identity)
        if prior:self._adopt(json.loads(prior[1]));return False
        if not self.can_write():raise ValueError('shadow capacity admission withheld')
        # Deleted zero credits are derived cache entries, not source evidence.
        # Retain prior displayed sizes: missing credit still means zero and an
        # unchanged quote cannot replenish consumed depth after recovery.
        for profile in state['profiles'].values():
            profile['credits']={k:v for k,v in profile['credits'].items() if v>EPS}
        if len(state['forecasts'])>512 or len(state['markets_seen'])>4096 or any(len(s['closed'])>2048 or len(s['seen'])>4096 or len(s['credits'])>32768 for s in state['profiles'].values()):raise ValueError('bounded research state exhausted; preserve and review')
        now=at(self.clock());state['sequence']+=1;state['last_at']=now.isoformat()
        if self.last and self.last['policy']!=self.policy:events=[{'type':'reviewed_source_transition','from':self.last['policy']['code_sha256'],'to':self.policy['code_sha256'],'scope':'Phase43: zero-credit cache compaction, passive new-entry retirement, settlement-aligned new independent entries, matched exits; original cash, losses, suspension, positions and immutable records retained'},*events]
        row=self.record_type(id=identity,timestamp=now,available_at=now,source=self.source_name,policy=self.policy,
            previous_id=self.last['id'] if self.last else None,previous_sha256=digest(self.last) if self.last else None,
            checkpoint=pack_checkpoint(state),state_sha256=digest(state),events=[{'type':'lossless_decision_batch','payload':pack_checkpoint({'decisions':events}),'sha256':digest(events)}],observations=observations)
        if len(row.model_dump_json().encode())>8*1024**2:raise ValueError('bounded shadow record exceeded')
        self.store.append(row)
        self.state,self.last=state,row.model_dump(mode='json');return True
    def enroll(self,forecasts,*,verifier):
        state=copy.deepcopy(self.state);events=[];now=at(self.clock())
        for f in forecasts:
            if f['id'] in state['forecasts']:
                if digest(f)!=digest(state['forecasts'][f['id']]):raise ValueError('original forecast mutation')
                continue
            if not at(f['evidence_cutoff'])<=at(f['timestamp'])<=now<at(f['event_end_time']):continue
            if f.get('research_only') is not True or f.get('trading_authority') is not False:raise ValueError('research-only forecast required')
            verifier(f);state['forecasts'][f['id']]=f;events.append({'type':'source_replayed_forecast','id':f['id'],'sha256':digest(f)})
        if events:return self._commit(state,events,{'operation':'prospective source enrollment'})
        return False
    @staticmethod
    def exposure(s,field=None,value=None):return sum(o.get('reserved',o.get('cost',0)) for o in [*s['orders'].values(),*s['positions'].values()] if field is None or o.get(field)==value)
    def budget(self,s,c,size):
        return max(0.,min(size,s['cash']-sum(o['reserved'] for o in s['orders'].values()),500*self.risk['aggregate_fraction']-self.exposure(s),
            500*self.risk['market_fraction']-self.exposure(s,'market_id',c['market']['market_id']),500*self.risk['event_fraction']-self.exposure(s,'event_id',c['market']['event_id']),
            500*self.risk['correlation_fraction']-self.exposure(s,'domain',c['domain'])))
    def credits(self,s,books):
        for token,b in books.items():
            old=s['books'].get(token)
            if old and at(b.timestamp)<at(old['at']):continue
            for side in ('asks','bids'):
                levels={str(p.price):p.size for p in getattr(b,side)};previous=old[side] if old else {}
                for price in levels.keys()|previous.keys():
                    key=f'{token}|{side}|{price}';size=levels.get(price,0.)
                    s['credits'][key]=min(size*self.policy['participation'],s['credits'].get(key,0)+max(0.,size-previous.get(price,0))*self.policy['participation'])
            s['books'][token]={'at':b.timestamp.isoformat(),'asks':{str(p.price):p.size for p in b.asks},'bids':{str(p.price):p.size for p in b.bids}}
    @staticmethod
    def exit_fee(position,fee,now):
        known=(fee.get('status')=='verified_current_protocol_curve' and fee.get('token_id')==position.get('token_id')
            and number(fee.get('rate'),0,1) and 0<=(now-at(fee['as_of'])).total_seconds()<=300)
        return ({**position,'rate':fee['rate']} if known else position),known

    def proceeds(self,s,p,b,*,consume):
        left=p['quantity'];value=0.;levels=[]
        for level in b.bids:
            key='|'.join((b.token_id,'bids',str(level.price)));q=min(left,s['credits'].get(key,0.))
            if q<=EPS:continue
            fee=round(q*p['rate']*level.price*(1-level.price),5);amount=q*(level.price-self.policy['extra_slippage_per_share'])-fee
            levels.append({'price':level.price,'quantity':q,'fee':fee});value+=amount;left-=q
            if consume:s['credits'][key]-=q
        return value,p['quantity']-left,levels
    def step(self,frame,fees,*,source_forecasts=None):
        now=at(self.clock());raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
        if raw.get('mode')!='real_market_data' or raw.get('producer_health',{}).get('status')!='ok' or not at(raw['timestamp'])<=at(raw['available_at'])<=now or (now-at(raw['available_at'])).total_seconds()>15:raise ValueError('fresh real frame required')
        if len(raw['markets'])>4096 or len(raw['books'])>4096:raise ValueError('bounded universe required')
        markets={m['token_id']:MarketSnapshot.model_validate(m) for m in raw['markets']};allbooks={b['token_id']:OrderBookSnapshot.model_validate(b) for b in raw['books']}
        if len(markets)!=len(raw['markets']) or len(allbooks)!=len(raw['books']):raise ValueError('ambiguous token identities')
        markets={t:m for t,m in markets.items() if m.status=='active' and m.end_time and m.end_time>now and m.resolution_rules and m.resolution_source and max(m.timestamp,m.available_at)<=now}
        books={t:b for t,b in allbooks.items() if t in markets and b.market_id==markets[t].market_id and b.source in PUBLIC_BOOK_SOURCES and assess_book(b,now,max_spread=.25,expected_token=t).healthy and len(b.asks)+len(b.bids)<=4096 and all(abs(l.price/markets[t].tick_size-round(l.price/markets[t].tick_size))<1e-7 for l in (*b.asks,*b.bids))}
        # Fixed bounded universe, prioritize executable depth, preserve open instruments.
        tournament_held={p['token_id'] for arm in self.state.get('exit_tournament',{}).get('arms',{}).values() for p in arm['positions'].values()}
        held=tournament_held|{p['token_id'] for s in self.state['profiles'].values() for p in [*s['positions'].values(),*s['orders'].values()]}
        if not self.entry_enrollment_open:
            markets={t:m for t,m in markets.items() if t in held};books={t:b for t,b in books.items() if t in held}
        supported={f['token_id'] for f in (source_forecasts if source_forecasts is not None else self.state['forecasts']).values()}
        ranked=sorted(markets,key=lambda t:(t not in held,t not in supported,-sum(l.size*l.price for l in books[t].asks[:5]) if t in books else 0,t))[:128]
        markets={t:markets[t] for t in ranked};books={t:b.model_copy(update={'bids':b.bids[:8],'asks':b.asks[:8]}) for t,b in books.items() if t in markets}
        state=copy.deepcopy(self.state);events=[]
        state['markets_seen']=sorted(set(state['markets_seen'])|{m.market_id for m in markets.values()})
        candidates,rejections=self.proposer(markets,books,source_forecasts if source_forecasts is not None else state['forecasts'],state['history'],state['prior_forecasts'],fees,now)
        if not self.entry_enrollment_open:
            candidates=[];rejections=[]
            for profile in state['profiles'].values():
                profile['books']={t:v for t,v in profile['books'].items() if t in held}
                profile['credits']={k:v for k,v in profile['credits'].items() if k.split('|',1)[0] in held}
        for token,b in books.items():
            history=state['history'].setdefault(token,[])
            if not history or at(history[-1]['at'])<b.timestamp:history.append({'at':b.timestamp.isoformat(),'mid':(b.bids[0].price+b.asks[0].price)/2,'bid':b.bids[0].price,'ask':b.asks[0].price,'book_sha256':digest(b.model_dump(mode='json'))})
            state['history'][token]=history[-32:]
        state['history']={t:h for t,h in state['history'].items() if t in markets}
        for f in sorted((source_forecasts if source_forecasts is not None else state['forecasts']).values(),key=lambda f:f['timestamp']):
            key=f['token_id']+'|'+f['model_id'];old=state['prior_forecasts'].get(key)
            if old is None or at(old['timestamp'])<=at(f['timestamp']):state['prior_forecasts'][key]=f
        for name,config in self.profile_configs.items():
            s=state['profiles'][name];self.credits(s,books);counts=Counter(s['counts']);rejects=Counter(s['rejects'])
            for r in rejections:rejects[r['strategy']+':'+r['reason']]+=1
            if s['day']!=now.date().isoformat():s['day']=now.date().isoformat();s['day_loss']=0.
            # Exit first, using remaining shared native bid depth; partial exits remain open.
            for oid,p in list(s['positions'].items()):
                b=books.get(p['token_id']);m=markets.get(p['token_id'])
                if not self.compatible(p,m) or b is None:continue
                exit_position,exit_fee_verified=self.exit_fee(p,fees.get(p['token_id'],{}),now)
                value,q,levels=self.proceeds(s,exit_position,b,consume=False)
                timeout=(now-at(p['entered_at'])).total_seconds()>=self.definitions[p['strategy']]['horizon']
                target=q>EPS and value>p['cost']*q/p['quantity']+.005*q
                stop=q>EPS and value<p['cost']*q/p['quantity']*.8
                if p.get('exit_policy')=='settlement_aligned_v43':
                    timeout=False
                    target=q>EPS and value>=p['target']*q
                if p['strategy']=='consistency' or not (target or timeout or stop) or b.timestamp<at(p['entered_at'])+timedelta(seconds=.5):continue
                value,q,levels=self.proceeds(s,exit_position,b,consume=True)
                if q<=EPS:continue
                cost=p['cost']*q/p['quantity'];p['cost']-=cost;p['quantity']-=q;s['cash']+=value;s['day_loss']+=value-cost
                closed={'strategy':p['strategy'],'event_id':p['event_id'],'forecast_id':p.get('forecast_id'),'pnl':value-cost,'cost':cost,'kind':'modeled_bid_exit','native_settled':False,'at':now.isoformat(),'exit_triggers':{'target':target,'timeout':timeout,'risk_stop':stop},'exit_policy':p.get('exit_policy','phase42_legacy'),'exit_fee_verified':exit_fee_verified,'exit_rate':exit_position['rate']}
                s['closed'].append(closed);counts[p['strategy']+':exits']+=1;events.append({'type':'modeled_exit','profile':name,'order_id':oid,'levels':levels,'book':b.model_dump(mode='json'),**closed})
                if p['quantity']<=EPS:del s['positions'][oid]
            # Pending limit orders require a later native snapshot; no quote-equals-fill shortcut.
            for oid,o in list(s['orders'].items()):
                if now>=at(o['expires']) or s['suspended']:
                    del s['orders'][oid];events.append({'type':'expired','profile':name,'id':oid});continue
                b=books.get(o['token_id']);m=markets.get(o['token_id'])
                if not self.compatible(o,m) or b is None or b.timestamp<at(o['created_at'])+timedelta(seconds=.5) or b.timestamp<at(s['books'][b.token_id]['at']):continue
                spent=0.;quantity=0.;levels=[]
                for level in b.asks:
                    if level.price>o['limit']+EPS:break
                    key='|'.join((b.token_id,'asks',str(level.price)))
                    q,cost,fee=self._size(level.price,min(s['credits'].get(key,0.),o['remaining']-quantity),max(0.,o['reserved']-spent),o['rate'])
                    if q<=EPS:continue
                    s['credits'][key]-=q;spent+=cost;quantity+=q;levels.append({'price':level.price,'quantity':q,'fee':fee,'displayed_size':level.size})
                if quantity>EPS:
                    p=s['positions'].setdefault(oid,{**{k:v for k,v in o.items() if k not in ('reserved','remaining')},'quantity':0.,'cost':0.,'entered_at':now.isoformat()})
                    p['quantity']+=quantity;p['cost']+=spent;p['last_fill_at']=now.isoformat();s['cash']-=spent;o['reserved']-=spent;o['remaining']-=quantity
                    counts[o['strategy']+':fills']+=1;events.append({'type':'modeled_fill','profile':name,'order_id':oid,'strategy':o['strategy'],'levels':levels,'cost':spent,'quantity':quantity,'book':b.model_dump(mode='json'),'actual_fill':False,'entry':copy.deepcopy(p)})
                    if o['remaining']<=EPS or o['reserved']<=EPS:del s['orders'][oid]
            # Executable liquidation marks; unknown full depth is never rendered as current profit.
            pnl=0.;markable=True;mark_s=copy.deepcopy(s)
            for p in s['positions'].values():
                b=books.get(p['token_id'])
                if b is None or not self.compatible(p,markets.get(p['token_id'])):markable=False;break
                mark_position,_=self.exit_fee(p,fees.get(p['token_id'],{}),now)
                value,q,_=self.proceeds(mark_s,mark_position,b,consume=True)
                if q+EPS<p['quantity']:markable=False;break
                p['marked_pnl']=value-p['cost'];p['marked_book_at']=min(b.timestamp,b.available_at).isoformat();pnl+=p['marked_pnl']
            s['unrealized']=pnl if markable else None
            equity=s['cash']+sum(p['cost'] for p in s['positions'].values())+pnl if markable else None
            if equity is not None:s['peak']=max(s['peak'],equity);s['drawdown']=max(s['drawdown'],s['peak']-equity)
            if s['drawdown']>=500*self.risk['drawdown_fraction'] or s['day_loss']<=-500*self.risk['daily_loss_fraction']:s['suspended']=True
            for c in sorted(candidates,key=lambda c:(c['strategy'],c['key'])):
                strategy=c['strategy'];counts[strategy+':candidates']+=1
                try:
                    token=c['token_id'];m=markets[token];b=books[token];key=strategy+':'+c['key']
                    if not self.entry_enrollment_open:raise ValueError('legacy_cohort_retired_from_new_entries; original_positions_losses_and_exit_policies_preserved')
                    if strategy=='spread_capture':raise ValueError('retired_crossed_ask_passive_proxy; adverse_selection_and_queue_position_unverified')
                    if s['suspended'] or (s['positions'] and not markable):raise ValueError('loss_stop_or_incomplete_portfolio_mark')
                    if key in s['seen'] or any(p['strategy']==strategy and p['token_id']==token for p in [*s['positions'].values(),*s['orders'].values()]):raise ValueError('already_enrolled_or_open')
                    closed=[p for p in s['closed'] if p['strategy']==strategy]
                    groups={p['event_id'] for p in closed}
                    if len(groups)>=20 and sum(p['pnl'] for p in closed)<0:raise ValueError('retired_negative_checkpoint; independent_review_still_required')
                    if b.asks[0].price-b.bids[0].price>config['spread']:raise ValueError('profile_spread')
                    fee=fees.get(token,{})
                    known=fee.get('status')=='verified_current_protocol_curve' and fee.get('token_id')==token and 0<=(now-at(fee['as_of'])).total_seconds()<=300
                    rate=fee['rate'] if known else config['unknown_fee']
                    if rate is None:raise ValueError('native_fee_unavailable')
                    if not number(rate,0,1):raise ValueError('invalid_fee_coefficient')
                    if name=='conservative' and (not c.get('forecast') or c['forecast'].get('calibration_status') not in ('qualified','calibrated')):raise ValueError('conservative_calibration_withheld')
                    target=c['target']
                    if c['probability'] is not None:
                        lower=c['forecast'].get('lower_probability',0.);target=target*(1-config['haircut'])+lower*config['haircut']
                    limit=c.get('limit',b.asks[0].price);budget=self.budget(s,c,config['size'])
                    quantity=0.;spent=0.;net=0.;last=None
                    for level in b.asks:
                        price=limit if c.get('passive') else level.price
                        if not c.get('passive') and level.price>limit+EPS:break
                        q,cost,_=self._size(price,level.size*self.policy['participation'],max(0.,budget-spent),rate)
                        # Pricing strategies reserve round-trip taker costs; passive fee also conservative.
                        exit_cost=rate*target*(1-target)+self.policy['extra_slippage_per_share'] if c['probability'] is None else 0.
                        if target-price-rate*price*(1-price)-.002-exit_cost<=config['edge']+EPS:break
                        quantity+=q;spent+=cost;net+=q*(target-exit_cost)-cost
                        if q>EPS:last=price
                        if c.get('passive'):break
                    if quantity+EPS<m.min_order_size or net<=EPS:raise ValueError('net_hypothesis_or_native_minimum_size')
                    if strategy!='consistency':
                        liquidation,exit_quantity,_=self.proceeds(s,{'quantity':quantity,'rate':rate},b,consume=False)
                        if exit_quantity+EPS<quantity:raise ValueError('entry_exit_risk_unobservable_at_intended_size')
                        if liquidation<spent*.8:raise ValueError('entry_liquidation_already_breaches_20pct_exit_rule')
                    oid=digest([name,key]);s['orders'][oid]={'id':oid,'strategy':strategy,'token_id':token,'market_id':m.market_id,'event_id':m.event_id,'domain':c['domain'],
                        'market':c['market'],'forecast_id':c.get('forecast',{}).get('id'),'created_at':now.isoformat(),'expires':(now+timedelta(seconds=30)).isoformat(),
                        'exit_policy':'settlement_aligned_v43' if strategy=='independent' else 'phase42_legacy','model_id':c.get('forecast',{}).get('model_id'),'model_sha256':c.get('forecast',{}).get('model_sha256'),
                        'fee_verified':known,'fee_evidence':fee if known else {'status':'assumed_sensitivity','rate':rate},'rate':rate,'reserved':spent,'remaining':quantity,'limit':last,'target':target,'bundle':c.get('bundle')}
                    s['seen'].append(key);counts[strategy+':orders']+=1
                    events.append({'type':'shadow_intent','profile':name,'order_id':oid,'quantity':quantity,'capital':spent,'estimated_net_value':net,'fee_verified':known,'candidate':c,'pricing_target_not_independent_probability':c['probability'] is None})
                except ValueError as error:
                    reason=str(error);rejects[strategy+':'+reason]+=1;events.append({'type':'rejection','profile':name,'strategy':strategy,'token_id':c['token_id'],'reason':reason})
            s['counts'],s['rejects']=dict(counts),dict(rejects)
        from neraium_poly.research.phase43 import economics, tournament
        experiment=state.setdefault('exit_tournament',tournament.initialize())
        tournament.advance(experiment,events,books,now,forecasts=source_forecasts,markets=markets)
        state['loss_ledger']=economics.ledger(events,state.get('loss_ledger'))
        pending={name+'|'+oid for name,s in state['profiles'].items() for oid in s['orders']}
        state['loss_ledger']['trades']={key:t for key,t in state['loss_ledger']['trades'].items() if t['quantity']>0 or key in pending}
        return self._commit(state,events,{'frame_id':raw['id'],'frame_available_at':raw['available_at'],'frame_sha256':digest(raw),'markets_evaluated':len(markets),'fresh_books':len(books),'candidates':len(candidates),'fees':fees})
    @staticmethod
    def compatible(p,m):
        return (m is not None and all(p['market'][k]==getattr(m,k) for k in ('market_id','event_id','token_id','question','resolution_rules','resolution_source','outcome','tick_size','min_order_size'))
            and at(p['market']['end_time'])==m.end_time)

    def settle(self,proofs):
        state=copy.deepcopy(self.state);events=[];now=at(self.clock())
        for fid,proof in proofs.items():
            f=state['forecasts'].get(fid)
            if f is None or fid in state['labels']:continue
            if (proof.get('forecast_id')!=fid or proof.get('native_payout_verified') is not True or proof.get('verified') is not True or not number(proof.get('payout'),0,1)
                or any(proof.get(k)!=f[k] for k in ('market_id','event_id','token_id','rules_sha256')) or not at(f['timestamp'])<at(proof['resolved_at'])<=at(proof['available_at'])<=now):raise ValueError('exact native proof required')
            state['labels'][fid]=proof
            events.append({'type':'verified_native_forecast_label','forecast_id':fid,'forecast_sha256':digest(f),'proof':proof,'positions_required':False})
            if 'exit_tournament' in state:
                from neraium_poly.research.phase43 import tournament
                tournament.settle(state['exit_tournament'],proof,now)
            for name,s in state['profiles'].items():
                for oid,p in list(s['positions'].items()):
                    if p['token_id']!=f['token_id'] or p['market_id']!=f['market_id'] or not self.compatible(p,MarketSnapshot.model_validate(f['market'])) or not at(p['last_fill_at'])<at(proof['resolved_at']):continue
                    value=p['quantity']*proof['payout'];s['cash']+=value
                    closed={'strategy':p['strategy'],'event_id':p['event_id'],'forecast_id':fid,'pnl':value-p['cost'],'cost':p['cost'],'kind':'native_verified_settlement','native_settled':True,'at':now.isoformat()}
                    s['closed'].append(closed);s['unrealized']=None if len(s['positions'])>1 else 0.;s['day_loss']+=closed['pnl'];del s['positions'][oid];s['orders'].pop(oid,None)
                    if s['day_loss']<=-500*self.risk['daily_loss_fraction']:s['suspended']=True
                    events.append({'type':'native_settlement','profile':name,'order_id':oid,'quantity':p['quantity'],'entry_forecast_id':p.get('forecast_id'),'proof':proof,**closed})
        if events:return self._commit(state,events,{'operation':'native payout replay'})
        return False
    def report(self):
        out={}
        for name,s in self.state['profiles'].items():
            mark_current=s['unrealized'] is not None and all(p.get('marked_book_at') and 0<=(at(self.clock())-at(p['marked_book_at'])).total_seconds()<=15 for p in s['positions'].values())
            strategies={}
            for strategy in self.definitions:
                closed=[p for p in s['closed'] if p['strategy']==strategy];positions=[p for p in s['positions'].values() if p['strategy']==strategy]
                strategies[strategy]={'screened_observations':s['counts'].get(strategy+':candidates',0)+sum(v for k,v in s['rejects'].items() if k.startswith(strategy+':')), 'unique_enrolled_opportunities':sum(k.startswith(strategy+':') for k in s['seen']), 'candidates':s['counts'].get(strategy+':candidates',0),'orders':s['counts'].get(strategy+':orders',0),'fill_events':s['counts'].get(strategy+':fills',0),
                    'open_positions':len(positions),'unrealized_net_pnl':sum(p.get('marked_pnl',0) for p in positions) if mark_current else None,'exposure':sum(p['cost'] for p in positions),'modeled_exit_net_pnl':sum(p['pnl'] for p in closed if not p['native_settled']),
                    'verified_settlement_net_pnl':sum(p['pnl'] for p in closed if p['native_settled']),'wins':sum(p['pnl']>0 for p in closed),'losses':sum(p['pnl']<0 for p in closed),'closed_observations':len(closed)}
            out[name]={'strategies':strategies,'cash_hypothetical':s['cash'],'exposure':self.exposure(s),'open_positions':len(s['positions']),'pending_orders':len(s['orders']),
                'unrealized_net_pnl':s['unrealized'] if mark_current else None,'maximum_drawdown':s['drawdown'],'suspended':s['suspended'],'rejections':s['rejects']}
        labels=[(self.state['forecasts'][fid],p) for fid,p in self.state['labels'].items() if number(self.state['forecasts'][fid].get('market_probability'),0,1) and p.get('payout') in (0,1)]
        scores=None
        if labels:
            import math
            def score(key):
                ps=[min(1-1e-12,max(1e-12,.5 if key=='neutral' else f[key])) for f,p in labels];ys=[p['payout'] for f,p in labels]
                return {'brier':sum((a-y)**2 for a,y in zip(ps,ys,strict=True))/len(ps),'log_loss':-sum(y*math.log(a)+(1-y)*math.log(1-a) for a,y in zip(ps,ys,strict=True))/len(ps)}
            scores={'model':score('probability'),'market':score('market_probability'),'neutral':score('neutral'),'forecast_count':len(labels),'native_parent_events':len({f['event_id'] for f,p in labels}),'reviewed_independent_events':0,'limitation':'descriptive only; dependency review and heldout validation missing; no calibration fit'}
        from neraium_poly.research.phase43 import economics, tournament
        economic_report={'loss_attribution':economics.attribution(self.state.get('loss_ledger',{'trades':{},'unmatched_exits':0})),
            'exit_tournament':tournament.report(self.state['exit_tournament'],at(self.clock())) if 'exit_tournament' in self.state else None,
            'strategy_changes':{'spread_capture':'retired for new intents: crossed-ask passive proxy without queue evidence; historical losses retained', 'independent':'new positions settlement-aligned with risk stop; old positions keep frozen legacy exits'},
            'next_milestone':'256 matched filled entries per profile or independent native resolutions; no automatic promotion; zero-credit compaction preserves the8MiB guard'}
        from neraium_poly.research.phase44.metrics import scores as grouped_scores
        return {**economic_report,'event_group_scores':grouped_scores(self.state['forecasts'],self.state['labels']),'as_of':self.state['last_at'],'markets_evaluated_unique':len(self.state['markets_seen']),'cycles':self.state['sequence'],'profiles':out,'verified_outcomes':len(self.state['labels']),'scoring_excluded_nonbinary_or_missing_baseline':len(self.state['labels'])-len(labels),'scores':scores,
            'forecasts':len(self.state['forecasts']),'strategy_policy_sha256':digest(self.policy),'parent_events':len({f['event_id'] for f in self.state['forecasts'].values()}),'hypotheses':self.definitions,'profiles_are_alternatives':True,'trading_authority':False,'actual_account_access':False,'calibration':'unvalidated; no fitted improvement claimed'}
