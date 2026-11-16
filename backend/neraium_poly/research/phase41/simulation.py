"""Alternative research portfolios. No broker, wallet, real account or stop access.

Profiles share observations, not liquidity or capital: each is a mutually
exclusive $500 scenario. Eligibility is NOT a calibrated/verified trading edge.
"""
import copy
import hashlib
import json
import math
import random
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

EPS=1e-9
PROFILES={
    'aggressive':{'minimum_edge':0.,'market_shrinkage':0.,'max_spread':.15,'assumed_unknown_fee_rate':.10},
    'balanced':{'minimum_edge':.005,'market_shrinkage':.25,'max_spread':.08,'assumed_unknown_fee_rate':None},
    'conservative':{'minimum_edge':.03,'market_shrinkage':0.,'max_spread':.05,'assumed_unknown_fee_rate':None},
}


class ProfileDeclaration(Record):
    policy:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False


class ProfileStudy(Record):
    declaration_id:str
    previous_id:str|None=None
    previous_sha256:str|None=None
    checkpoint:dict
    checkpoint_sha256:str
    events:list
    inputs:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


def number(value,low=0.,high=float('inf')):
    return type(value) in (int,float) and math.isfinite(value) and low<=value<=high


class ProfileExperiment:
    def __init__(self,store,*,clock,risk_limits,can_write):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.risk=dict(risk_limits)
        if self.risk['bankroll']!=500 or not number(self.risk['aggregate_fraction'],0,.2):raise ValueError('approved500USD/20percent research budgets required')
        if any(not number(self.risk[k],0,cap) for k,cap in {'market_fraction':.05,'event_fraction':.1,'correlation_fraction':.1,'daily_loss_fraction':.05,'drawdown_fraction':.1}.items()):raise ValueError('approved risk ceilings required')
        self.policy={'version':'phase41-paired-profiles-v1','code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'profiles':PROFILES,'risk_limits':self.risk,'capital_scope':'mutually exclusive hypothetical500USD alternatives, never pooled or funded accounts',
            'latency_seconds':.5,'order_ttl_seconds':30,'participation':min(.1,self.risk['max_liquidity_participation']),'notional':5.,'extra_slippage_per_share':.0015,
            'redemption_reserve_per_share':.0005,'forecast_max_age_seconds':300,
            'fill_model':'new native snapshot after latency; observed growth credits only; no same-snapshot refill',
            'fees':'current native curve if verified; aggressive-only assumed10percent coefficient when unavailable; nearest5decimals per modeled level fill',
            'promotion':'research recommendation only after independent chronological held-out results; no automatic certification or trading authority'}
        self.identity=digest(self.policy);self.last=None
        now=at(clock());prior=store.get(self.identity)
        if prior is None:
            if not can_write():raise ValueError('profile storage unavailable')
            store.append(ProfileDeclaration(id=self.identity,timestamp=now,available_at=now,source='neraium-poly/shadow-profiles/v41',policy=self.policy))
        else:
            if json.loads(prior[1])['policy']!=self.policy:raise ValueError('profile policy mismatch; no reset')
        rows=store.latest('ProfileStudy',1)
        self.state={'sequence':0,'last_at':None,'cohort':{},'labels':{},'closed':[], 'profiles':{n:{'cash':500.,'orders':{},'positions':{},'seen':[],
            'credits':{},'last_books':{},'realized_pnl':0.,'settlements':0,'fills':0,'order_count':0,'expired':0,
            'rejections':{},'fees':0.,'unrealized_pnl':None,'max_drawdown':0.,'peak_equity':500.,
            'day':now.date().isoformat(),'day_realized':0.,'suspended':False} for n in PROFILES}}
        if rows:self._adopt(rows[0])

    def _adopt(self,row):
        row=ProfileStudy.model_validate(row);state=unpack_checkpoint(row.checkpoint)
        if row.declaration_id!=self.identity or digest(state)!=row.checkpoint_sha256 or at(row.available_at)>at(self.clock()):raise ValueError('profile checkpoint mismatch')
        if row.previous_id:
            previous=self.store.get(row.previous_id)
            if previous is None or digest(json.loads(previous[1]))!=row.previous_sha256:raise ValueError('profile chain mismatch')
        self.state,self.last=state,row.model_dump(mode='json')

    def _commit(self,state,events,inputs):
        now=at(self.clock());identity=f'profile:{self.identity}:{self.state["sequence"]+1:012d}'
        if self.state['last_at'] and now<at(self.state['last_at']):raise ValueError('profile clock regression')
        prior=self.store.get(identity)
        if prior is not None:self._adopt(json.loads(prior[1]));return False
        if not self.can_write():raise ValueError('profile storage backpressure')
        state['sequence']=self.state['sequence']+1;state['last_at']=now.isoformat()
        if len(state['cohort'])>1024 or any(len(s['credits'])>16384 or len(s['positions'])>128 or len(s['orders'])>128 for s in state['profiles'].values()):raise ValueError('bounded profile state exhausted')
        row=ProfileStudy(id=identity,timestamp=now,available_at=now,source='neraium-poly/shadow-profiles/v41',declaration_id=self.identity,
            previous_id=self.last['id'] if self.last else None,previous_sha256=digest(self.last) if self.last else None,
            checkpoint=pack_checkpoint(state),checkpoint_sha256=digest(state),events=events,inputs=inputs)
        if len(row.model_dump_json().encode())>8*1024**2:raise ValueError('profile record byte cap')
        self.store.append(row);self.state,self.last=state,row.model_dump(mode='json');return True

    def enroll(self,forecasts,*,verifier):
        state=copy.deepcopy(self.state);events=[];declared=json.loads(self.store.get(self.identity)[1])['available_at']
        for f in forecasts:
            if f['id'] in state['cohort']:
                if digest(f)!=digest(state['cohort'][f['id']]):raise ValueError('immutable forecast conflict')
                continue
            if (not at(declared)<=at(f['timestamp'])<=at(self.clock()) or not at(f['evidence_cutoff'])<=at(f['timestamp'])<at(f['event_end_time']) or not f.get('evidence_ids') or not number(f['probability'],0,1)
                or f.get('research_only') is not True or f.get('trading_authority') is not False or f.get('certification_authority') is not False):raise ValueError('prospective independent source forecast required')
            verifier(f)
            state['cohort'][f['id']]=copy.deepcopy(f);events.append({'type':'source_replayed_enrollment','forecast_id':f['id'],'forecast_sha256':digest(f)})
        return self._commit(state,events,{'cohort_sha256':digest(state['cohort'])})

    @staticmethod
    def exposure(s,field=None,value=None):
        return sum(x.get('reserved',x.get('cost',0.)) for x in [*s['orders'].values(),*s['positions'].values()] if field is None or x.get(field)==value)

    def _budget(self,s,f):
        capital=self.risk['bankroll']
        return max(0.,min(5.,s['cash']-sum(o['reserved'] for o in s['orders'].values()),
            capital*self.risk['aggregate_fraction']-self.exposure(s),
            capital*self.risk['market_fraction']-self.exposure(s,'market_id',f['market_id']),
            capital*self.risk['event_fraction']-self.exposure(s,'event_id',f['event_id']),
            capital*self.risk['correlation_fraction']-self.exposure(s,'domain',f['domain'])))

    def _cost(self,price,quantity,rate):
        fee=round(quantity*rate*price*(1-price),5)
        reserves=quantity*(self.policy['extra_slippage_per_share']+self.policy['redemption_reserve_per_share'])
        return price*quantity+fee+reserves,fee

    def _size(self,price,maximum,budget,rate):
        unit=price+rate*price*(1-price)+self.policy['extra_slippage_per_share']+self.policy['redemption_reserve_per_share']
        q=min(maximum,max(0.,budget)/unit);cost,fee=self._cost(price,q,rate)
        if cost>budget+EPS:
            low,high=0.,q
            for _ in range(40):
                mid=(low+high)/2
                if self._cost(price,mid,rate)[0]<=budget:low=mid
                else:high=mid
            q=low;cost,fee=self._cost(price,q,rate)
        return q,cost,fee

    def _quote(self,f,markets,books,now,spread):
        m=markets.get(f['token_id']);b=books.get(f['token_id']);old=f['market']
        if m is None or b is None:raise ValueError('current_book_missing')
        if (any(getattr(m,k)!=old.get(k) for k in ('market_id','event_id','token_id','question','resolution_rules','resolution_source','outcome'))
            or m.tick_size!=old.get('tick_size') or m.min_order_size!=old.get('min_order_size')
            or m.end_time!=at(old['end_time']) or max(m.timestamp,m.available_at)>now
            or m.status!='active' or not m.end_time or min(m.end_time,at(f['event_end_time']))<=now):raise ValueError('current_contract_identity_or_lifecycle')
        if b.market_id!=m.market_id or b.source not in PUBLIC_BOOK_SOURCES or not assess_book(b,now,max_spread=spread,expected_token=m.token_id).healthy:raise ValueError('current_book_quality')
        if any(abs(p.price/m.tick_size-round(p.price/m.tick_size))>1e-7 for p in (*b.asks,*b.bids)):raise ValueError('native_price_tick')
        return m,b

    def _credits(self,s,books,now):
        for token,b in books.items():
            if b.source not in PUBLIC_BOOK_SOURCES or not assess_book(b,now,max_spread=1.,expected_token=token).healthy:continue
            previous=s['last_books'].get(token)
            if previous and at(b.timestamp)<at(previous['at']):continue
            levels={str(p.price):p.size for p in b.asks}
            old=previous['levels'] if previous else {}
            for price in set(levels)|set(old):
                key=token+'|'+price;size=levels.get(price,0.);growth=max(0.,size-old.get(price,0.))*self.policy['participation']
                s['credits'][key]=min(size*self.policy['participation'],s['credits'].get(key,0.)+growth)
            s['last_books'][token]={'at':b.timestamp.isoformat(),'id':b.id,'levels':levels}

    def _mark(self,s,books,now):
        pnl=0.;used={}
        for p in s['positions'].values():
            b=books.get(p['token_id'])
            if b is None or b.market_id!=p['market_id'] or b.source not in PUBLIC_BOOK_SOURCES or not assess_book(b,now,max_spread=1.,expected_token=p['token_id']).healthy:
                s['unrealized_pnl']=None;return
            remaining=p['quantity'];proceeds=0.
            for level in b.bids:
                key=(b.token_id,level.price);q=min(remaining,max(0.,level.size*self.policy['participation']-used.get(key,0.)))
                if q<=EPS:continue
                used[key]=used.get(key,0.)+q;remaining-=q
                fee=round(q*p['fee_rate']*level.price*(1-level.price),5)
                proceeds+=q*(level.price-self.policy['extra_slippage_per_share'])-fee
            if remaining>EPS:s['unrealized_pnl']=None;return
            pnl+=proceeds-p['cost']
        s['unrealized_pnl']=pnl
        equity=s['cash']+sum(p['cost'] for p in s['positions'].values())+pnl
        s['peak_equity']=max(s['peak_equity'],equity);s['max_drawdown']=max(s['max_drawdown'],s['peak_equity']-equity)
        if s['max_drawdown']>=500*self.risk['drawdown_fraction']-EPS:s['suspended']=True

    def step(self,frame,fee_proofs,*,conservative_verifier=None):
        now=at(self.clock());raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
        if raw.get('mode')!='real_market_data' or raw.get('producer_health',{}).get('status')!='ok' or not at(raw['timestamp'])<=at(raw['available_at'])<=now or not 0<=(now-at(raw['available_at'])).total_seconds()<=15:raise ValueError('fresh genuine frame required')
        if len(raw['markets'])>4096 or len(raw['books'])>4096:raise ValueError('bounded profile frame required')
        markets={m['token_id']:MarketSnapshot.model_validate(m) for m in raw['markets']};books={b['token_id']:OrderBookSnapshot.model_validate(b) for b in raw['books']}
        if len(markets)!=len(raw['markets']) or len(books)!=len(raw['books']):raise ValueError('ambiguous native identities')
        tokens={f['token_id'] for f in self.state['cohort'].values()};books={t:b for t,b in books.items() if t in tokens}
        if any(len(b.bids)+len(b.asks)>4096 for b in books.values()) or sum(len(b.bids)+len(b.asks) for b in books.values())>100000:raise ValueError('bounded profile book depth required')
        state=copy.deepcopy(self.state);events=[]
        for name,config in PROFILES.items():
            s=state['profiles'][name];self._credits(s,books,now);self._mark(s,books,now)
            if s['day']!=now.date().isoformat():s['day']=now.date().isoformat();s['day_realized']=0.
            for oid,o in list(s['orders'].items()):
                if s['suspended'] or now>=at(o['expires_at']):
                    del s['orders'][oid];s['expired']+=1;events.append({'type':'expired_or_suspended','profile':name,'order_id':oid});continue
                try:m,b=self._quote(state['cohort'][o['forecast_id']],markets,books,now,config['max_spread'])
                except ValueError:continue
                if b.timestamp<at(o['created_at'])+timedelta(seconds=self.policy['latency_seconds']):continue
                if b.timestamp<at(s['last_books'][b.token_id]['at']):continue
                quantity=0.;spent=0.;fees=0.;levels=[]
                for level in b.asks:
                    if level.price>o['limit_price']+EPS:break
                    key=b.token_id+'|'+str(level.price)
                    q,cost,fee=self._size(level.price,min(s['credits'].get(key,0.),o['remaining_quantity']-quantity),max(0.,o['reserved']-spent),o['fee_rate'])
                    if q<=EPS:continue
                    if cost>o['reserved']-spent+EPS:continue
                    s['credits'][key]-=q;quantity+=q;spent+=cost;fees+=fee;levels.append({'price':level.price,'quantity':q,'displayed_size':level.size,'modeled_fee':fee})
                if quantity>EPS:
                    p=s['positions'].setdefault(oid,{k:v for k,v in o.items() if k not in ('reserved','remaining_quantity','limit_price')})
                    p['quantity']=p.get('quantity',0.)+quantity;p['cost']=p.get('cost',0.)+spent;p['last_fill_at']=now.isoformat()
                    s['cash']-=spent;s['fees']+=fees;s['fills']+=1;o['reserved']-=spent;o['remaining_quantity']-=quantity
                    events.append({'type':'hypothetical_fill','profile':name,'order_id':oid,'quantity':quantity,'cost':spent,'levels':levels,
                        'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'book_at':b.timestamp.isoformat(),'actual_fill':False})
                    if o['remaining_quantity']<=EPS or o['reserved']<=EPS:del s['orders'][oid]
            self._mark(s,books,now)
            rejections=Counter(s['rejections'])
            for fid,f in sorted(state['cohort'].items()):
                try:
                    if fid in s['seen']:raise ValueError('already_enrolled_profile_forecast')
                    if s['suspended'] or s['day_realized']<=-500*self.risk['daily_loss_fraction']:raise ValueError('shadow_loss_or_drawdown_stop')
                    if s['positions'] and s['unrealized_pnl'] is None:raise ValueError('incomplete_executable_portfolio_mark')
                    if not 0<=(now-at(f['timestamp'])).total_seconds()<=300:raise ValueError('forecast_stale')
                    m,b=self._quote(f,markets,books,now,config['max_spread'])
                    fee=fee_proofs.get(m.token_id,{})
                    known=fee.get('status')=='verified_current_protocol_curve' and fee.get('token_id')==m.token_id and 0<=(now-at(fee['as_of'])).total_seconds()<=300
                    rate=fee['rate'] if known else config['assumed_unknown_fee_rate']
                    if rate is None or not number(rate,0,1):raise ValueError('current_native_fee_unavailable')
                    if name=='conservative':
                        if conservative_verifier is None or conservative_verifier(f,raw,now) is not True:raise ValueError('conservative_calibration_and_full_cost_proofs_required')
                        probability=f['lower_probability']
                    else:
                        mid=(b.bids[0].price+b.asks[0].price)/2
                        probability=f['probability']*(1-config['market_shrinkage'])+mid*config['market_shrinkage']
                    budget=self._budget(s,f)
                    if budget<2-EPS:raise ValueError('approved_exposure_or_concentration_budget')
                    quantity=0.;spend=0.;limit=None;expected=0.
                    for level in b.asks:
                        unit=level.price+rate*level.price*(1-level.price)+self.policy['extra_slippage_per_share']+self.policy['redemption_reserve_per_share']
                        if probability-unit<=config['minimum_edge']+EPS:break
                        q,cost,_=self._size(level.price,level.size*self.policy['participation'],max(0.,budget-spend),rate)
                        quantity+=q;spend+=cost;expected+=q*probability-cost
                        if q>EPS:limit=level.price
                    if quantity+EPS<m.min_order_size or expected<=EPS:raise ValueError('positive_modeled_net_value_at_native_minimum_not_established')
                    oid=digest([self.identity,name,fid]);s['seen'].append(fid);s['order_count']+=1
                    s['orders'][oid]={'id':oid,'forecast_id':fid,'domain':f['domain'],'event_id':f['event_id'],'market_id':m.market_id,'token_id':m.token_id,
                        'rules_sha256':f['rules_sha256'],'created_at':now.isoformat(),'expires_at':min(now+timedelta(seconds=30),at(f['event_end_time'])).isoformat(),
                        'remaining_quantity':quantity,'reserved':spend,'limit_price':limit,'fee_rate':rate,'fee_verified':known,'modeled_probability':probability}
                    events.append({'type':'shadow_order_intent','profile':name,'order_id':oid,'forecast_id':fid,'quantity':quantity,'reserved':spend,
                        'modeled_expected_net_value':expected,'decision_probability':probability,'original_model_probability':f['probability'],
                        'uncertainty':f.get('uncertainty',{'lower':f.get('lower_probability'),'upper':f.get('upper_probability')}),
                        'conditional_reference_assumptions':{k:f.get(k) for k in ('conditioning','target_conditioning','unconditional_contract_probability','probability_semantics')},'calibration_status':f.get('calibration_status'),
                        'fee_basis':'verified_native_curve' if known else 'assumed10percent_coefficient','cost_reserves_are_assumptions':True,
                        'book_id':b.id,'validated_profitability':False,'execution_authority':False})
                except (ValueError,KeyError,TypeError) as error:
                    reason=str(error)[:160];rejections[reason]+=1;events.append({'type':'rejected','profile':name,'forecast_id':fid,'reason':reason})
            s['rejections']=dict(rejections)
        tokens={f['token_id'] for f in state['cohort'].values()}
        return self._commit(state,events,{'original_frame_id':raw['id'],'cohort_sha256':digest(state['cohort']),
            'frame':{**{k:v for k,v in raw.items() if k not in ('markets','books')},'markets':[m for m in raw['markets'] if m['token_id'] in tokens],
                     'books':[b for b in raw['books'] if b['token_id'] in tokens]},'fee_proofs':fee_proofs})

    def settle(self,verifier):
        state=copy.deepcopy(self.state);events=[];now=at(self.clock())
        for fid,f in state['cohort'].items():
            if fid in state['labels']:continue
            proof=verifier(f,now)
            if proof is None:continue
            if (proof.get('verified') is not True or proof.get('native_payout_verified') is not True
                or any(proof.get(k)!=f[k] for k in ('market_id','token_id','event_id','rules_sha256')) or proof.get('forecast_id')!=fid
                or not at(f['timestamp'])<at(proof['resolved_at'])<=at(proof['available_at'])<=now or not number(proof.get('payout'),0,1)):
                raise ValueError('native verified chronological cohort label required')
            state['labels'][fid]=proof;events.append({'type':'native_verified_cohort_label','forecast_id':fid,'proof':proof})
        for name,s in state['profiles'].items():
            if s['day']!=now.date().isoformat():s['day']=now.date().isoformat();s['day_realized']=0.
            for oid,p in list(s['positions'].items()):
                proof=state['labels'].get(p['forecast_id'])
                if proof is None:continue
                if (proof.get('verified') is not True or any(proof.get(k)!=p[k] for k in ('forecast_id','market_id','token_id','event_id','rules_sha256'))
                    or not at(p['last_fill_at'])<at(proof['resolved_at'])<=at(proof['available_at'])<=now or not number(proof.get('payout'),0,1)):
                    raise ValueError('native verified chronological payout required')
                received=p['quantity']*proof['payout'];pnl=received-p['cost'];s['cash']+=received;s['realized_pnl']+=pnl;s['day_realized']+=pnl;s['settlements']+=1
                if s['day_realized']<=-500*self.risk['daily_loss_fraction']:s['suspended']=True
                state['closed'].append({'profile':name,'forecast_id':p['forecast_id'],'realized_pnl':pnl,'cost':p['cost'],'decision_at':p['created_at']})
                del s['positions'][oid];s['orders'].pop(oid,None)
                events.append({'type':'native_verified_shadow_settlement','profile':name,'position_id':oid,'realized_simulated_pnl':pnl,'proof':proof})
            s['unrealized_pnl']=None if s['positions'] else 0.
            if not s['positions']:
                s['peak_equity']=max(s['peak_equity'],s['cash']);s['max_drawdown']=max(s['max_drawdown'],s['peak_equity']-s['cash'])
        if events:return self._commit(state,events,{'scope':'native source replay; official event result alone is insufficient'})
        return False

    def promotion(self):
        declared=at(json.loads(self.store.get(self.identity)[1])['available_at']);heldout_start=declared+timedelta(days=1)
        groups={};matured_missing=0
        training_events={f['event_id'] for f in self.state['cohort'].values() if at(f['timestamp'])<heldout_start}
        training_groups={p.get('reviewed_dependency_group') for fid,p in self.state['labels'].items() if at(self.state['cohort'][fid]['timestamp'])<heldout_start}
        for fid,f in self.state['cohort'].items():
            if at(f['timestamp'])<heldout_start:continue
            label=self.state['labels'].get(fid)
            if label is None:
                matured_missing+=at(f['event_end_time'])<=at(self.clock());continue
            group=label.get('reviewed_dependency_group')
            if label.get('independence_reviewed') is True and group and group not in training_groups and f['event_id'] not in training_events:groups.setdefault(group,[]).append(fid)
        candidates=[]
        if len(groups)>=20 and not matured_missing:
            for name in PROFILES:
                returns=[sum(c['realized_pnl'] for c in self.state['closed'] if c['profile']==name and c['forecast_id'] in ids) for ids in groups.values()]
                rng=random.Random(41);means=sorted(sum(rng.choices(returns,k=len(returns)))/len(returns) for _ in range(1000))
                lower=means[int(1000*.05/len(PROFILES))]  # grouped, one-sided Bonferroni across the3 frozen profiles.
                candidates.append({'profile':name,'mean_group_simulated_pnl':sum(returns)/len(returns),'corrected_bootstrap_lower':lower})
        positive=[r for r in candidates if r['corrected_bootstrap_lower']>0]
        return {'heldout_start':heldout_start.isoformat(),'reviewed_oos_groups':len(groups),'matured_missing_labels':matured_missing,
            'research_recommendation':max(positive,key=lambda r:r['mean_group_simulated_pnl'])['profile'] if positive else None,
            'oos_results':candidates,'method':'common native-labeled cohort, reviewed dependence groups, zero returns for no-trade groups;1000group bootstrap draws;3-profile Bonferroni; min20heldout groups',
            'scope':'research profile preference only; modeled fills/costs are not demonstrated real returns; no certification or trading authority'}

    def report(self):
        result={}
        for name,s in self.state['profiles'].items():
            result[name]={'orders':s['order_count'],'fill_events':s['fills'],'open_orders':len(s['orders']),'open_positions':len(s['positions']),
                'cash_hypothetical':s['cash'],'exposure':self.exposure(s),'fees_modeled':s['fees'],
                'realized_simulated_pnl':s['realized_pnl'] if s['settlements'] else None,'unrealized_simulated_pnl':s['unrealized_pnl'] if s['fills'] else None,
                'maximum_drawdown':s['max_drawdown'] if s['fills'] else None,'settled_positions':s['settlements'],'suspended':s['suspended'],'rejections':s['rejections']}
            result[name]['capital_utilization']=self.exposure(s)/500
            result[name]['marked_equity']=s['cash']+sum(p['cost'] for p in s['positions'].values())+s['unrealized_pnl'] if s['unrealized_pnl'] is not None else None
        return {'profiles':result,'policy_id':self.identity,'cohort_forecasts':len(self.state['cohort']),
            'parent_events':len({f['event_id'] for f in self.state['cohort'].values()}),'reviewed_independent_events':0,
            'profile_capital_is_not_additive':True,'verified_cohort_labels':len(self.state['labels']),'promotion':self.promotion(),
            'actual_account_access':False,'trading_authority':False,'scope':'prospective assumption-dependent shadow execution, not actual fills or proven edge'}
