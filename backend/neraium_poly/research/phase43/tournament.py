"""Frozen matched-entry exit policies. Alternative experiments, never additive capital.

Enrollment occurs only AFTER a modeled fill on a later authentic native book.
Every arm receives identical entry cost/quantity. Each arm separately shares
10% observed growth-only liquidity across its positions. Missing depth withholds
an exit; unresolved holds never become settled profit. No financial accounts.
"""
import hashlib
from datetime import timedelta

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at

ARMS = ('hold_native', 'first_executable_bid', 'evidence_repricing', 'time_300s', 'risk_20pct')
POLICY = {'version': 'phase43-matched-exits-v1', 'arms': ARMS,
          'participation': .1, 'slippage_per_share': .0015, 'latency_seconds': .5,
          'max_entries': 256, 'selection': 'first256 actual new modeled filled orders per profile; no winner selection or automatic promotion',
          'comparison': 'alternative exit paths on identical entries, not five funded accounts; model fees retained; no queue or exchange-fill claim',
          'evidence_repricing': 'fresh same-model external probability revision below net bid, or net bid reaches frozen entry probability target',
          'risk_budgets_usd': {'aggregate':100.,'market':25.,'event':50.,'correlation':50.},
          'checkpoint': '256 entries per profile is a fixed review checkpoint; no automatic clearing'}


def initialize():
    return {'policy_sha256': digest(POLICY), 'entries': {}, 'fill_counts': {}, 'withheld_fills': 0, 'withholding_reasons': {}, 'arms': {a: {'positions': {}, 'closed': [], 'books': {}, 'credits': {}, 'cash':{}, 'maximum_drawdown':{}, 'peak':{}, 'loss_today':{}, 'day':None, 'suspended':{}} for a in ARMS}}


def advance(state, events, books, now, *, forecasts=None, markets=None):
    """books are already fresh, identity-bound, eight-level native snapshots."""
    if state['policy_sha256'] != digest(POLICY):
        raise ValueError('frozen exit tournament policy mismatch')
    forecasts = forecasts or {}
    eligible_tokens={p['token_id'] for arm in state['arms'].values() for p in arm['positions'].values()} | {e['book']['token_id'] for e in events if e['type']=='modeled_fill'}
    books={t:b for t,b in books.items() if t in eligible_tokens}
    for arm in state['arms'].values():
        if arm['day']!=now.date().isoformat():
            arm['day']=now.date().isoformat();arm['loss_today']={}
        for token, b in books.items():
            old = arm['books'].get(token)
            if old and at(b.timestamp) <= at(old['at']):
                continue
            previous = old['bids'] if old else {}
            levels = {str(p.price): p.size for p in b.bids}
            for price in previous.keys() | levels.keys():
                size = levels.get(price, 0.)
                for profile in ('aggressive','balanced','conservative'):
                    key=profile+'|'+token+'|'+price
                    credit = min(size * .1, arm['credits'].get(key, 0.) + max(0., size - previous.get(price, 0.)) * .1)
                    if credit > 1e-8: arm['credits'][key] = credit
                    else: arm['credits'].pop(key, None)
            arm['books'][token] = {'at': b.timestamp.isoformat(), 'bids': levels}
    for e in events:
        if e['type'] != 'modeled_fill':
            continue
        key = e['profile'] + '|' + e['order_id']
        profile=e['profile'];incoming=e['entry']
        rejected=False
        for arm in state['arms'].values():
            ps=[p for p in arm['positions'].values() if p['profile']==profile]
            totals={'aggregate':sum(p['cost'] for p in ps), 'market':sum(p['cost'] for p in ps if p['market_id']==incoming['market_id']),
                    'event':sum(p['cost'] for p in ps if p['event_id']==incoming['event_id']), 'correlation':sum(p['cost'] for p in ps if p['domain']==incoming['domain'])}
            rejected |= arm['suspended'].get(profile,False) or arm['cash'].get(profile,500.)<e['cost'] or any(v+e['cost']>POLICY['risk_budgets_usd'][k]+1e-8 for k,v in totals.items())
        if rejected:
            state['withheld_fills']+=1;state['withholding_reasons']['matched_all_arm_risk_budget']=state['withholding_reasons'].get('matched_all_arm_risk_budget',0)+1
            continue
        if state['fill_counts'].get(e['profile'],0)>=POLICY['max_entries']:
            state['withheld_fills']+=1
            continue
        state['fill_counts'][e['profile']]=state['fill_counts'].get(e['profile'],0)+1
        entry = state['entries'].get(key)
        if entry is None:
            if sum(k.startswith(e['profile']+'|') for k in state['entries']) >= POLICY['max_entries']:
                continue
            # Details are attached by the engine from the authenticated entry order.
            p = e['entry']
            entry = state['entries'][key] = {'profile': e['profile'], 'order_id': e['order_id'],
                'strategy': p['strategy'], 'domain':p['domain'], 'market_id': p['market_id'], 'event_id': p['event_id'],
                'token_id': p['token_id'], 'rules_sha256': hashlib.sha256(p['market']['resolution_rules'].encode()).hexdigest(),
                'binding_sha256': binding(p['market']),
                'model_id': p.get('model_id'), 'model_sha256': p.get('model_sha256'), 'forecast_id': p.get('forecast_id'),
                'target': p['target'], 'rate': p['rate'], 'at': now.isoformat(),
                'quantity': 0., 'cost': 0., 'source_book_sha256': digest(e['book'])}
        entry['quantity'] += e['quantity']; entry['cost'] += e['cost']
        for arm in state['arms'].values():
            arm['cash'][profile]=arm['cash'].get(profile,500.)-e['cost']
            # A partially filled pending order must not reopen an already exited
            # cohort. Each fill is its own matched lot with deterministic ID.
            lot = key + '|' + e['book']['id']
            if lot in arm['positions'] or any(c['lot'] == lot for c in arm['closed']):
                raise ValueError('duplicate tournament fill')
            arm['positions'][lot] = {**entry, 'quantity': e['quantity'], 'cost': e['cost'], 'at': now.isoformat(), 'last_mark': None}
    for name, arm in state['arms'].items():
        for lot, p in list(arm['positions'].items()):
            b = books.get(p['token_id'])
            if b is None or markets is None or p['token_id'] not in markets or binding(markets[p['token_id']].model_dump(mode='json'))!=p['binding_sha256'] or b.market_id != p['market_id'] or b.timestamp < at(p['at']) + timedelta(seconds=.5):
                p['last_mark'] = None
                continue
            left = p['quantity']; value = 0.; levels = []
            for level in b.bids:
                key = p['profile']+'|'+p['token_id'] + '|' + str(level.price)
                q = min(left, arm['credits'].get(key, 0.))
                if q <= 1e-8: continue
                fee = round(q*p['rate']*level.price*(1-level.price), 5)
                value += q*(level.price-.0015)-fee; left -= q
                levels.append({'price': level.price, 'quantity': q, 'fee': fee})
            q = p['quantity']-left
            if q <= 1e-8:
                p['last_mark'] = None
                continue
            cost = p['cost']*q/p['quantity']
            revision = any(f.get('model_id') == p['model_id'] and f.get('model_sha256') == p.get('model_sha256') and f.get('market_id') == p['market_id'] and f.get('token_id') == p['token_id']
                           and at(p['at']) < at(f['timestamp']) <= now and at(f['evidence_cutoff']) <= at(f['timestamp'])
                           and 0 <= (now-at(f['timestamp'])).total_seconds() <= 300 and f['probability'] < value/q for f in forecasts.values())
            trigger = (name == 'first_executable_bid' or name == 'time_300s' and (now-at(p['at'])).total_seconds() >= 300
                       or name == 'risk_20pct' and value < cost*.8
                       or name == 'evidence_repricing' and (revision or value >= p['target']*q))
            p['last_mark'] = {'at': now.isoformat(), 'book_sha256': digest(b.model_dump(mode='json')),
                              'net_pnl': value-p['cost'] if left <= 1e-8 else None, 'executable_quantity': q}
            if not trigger: continue
            for level in levels: arm['credits'][p['profile']+'|'+p['token_id']+'|'+str(level['price'])] -= level['quantity']
            arm['closed'].append({'lot': lot, 'profile': p['profile'], 'strategy': p['strategy'], 'event_id': p['event_id'],
                'quantity': q, 'cost': cost, 'pnl': value-cost, 'at': now.isoformat(), 'native_settled': False,
                'book_sha256': digest(b.model_dump(mode='json')), 'levels': levels})
            arm['cash'][p['profile']]=arm['cash'].get(p['profile'],500.)+value
            arm['loss_today'][p['profile']]=arm['loss_today'].get(p['profile'],0.)+value-cost
            if arm['loss_today'][p['profile']]<=-25.:arm['suspended'][p['profile']]=True
            p['quantity'] -= q; p['cost'] -= cost
            if p['quantity'] <= 1e-8: del arm['positions'][lot]
        remaining=dict(arm['credits'])
        for p in arm['positions'].values():
            b=books.get(p['token_id']);p['last_mark']=None
            if b is None or markets is None or p['token_id'] not in markets or binding(markets[p['token_id']].model_dump(mode='json'))!=p['binding_sha256']:continue
            left=p['quantity'];value=0.
            for level in b.bids:
                key=p['profile']+'|'+p['token_id']+'|'+str(level.price);q=min(left,remaining.get(key,0.))
                if q<=1e-8:continue
                remaining[key]-=q;left-=q;value+=q*(level.price-.0015)-round(q*p['rate']*level.price*(1-level.price),5)
            p['last_mark']={'at':now.isoformat(),'book_sha256':digest(b.model_dump(mode='json')),'net_pnl':value-p['cost'] if left<=1e-8 else None,'executable_quantity':p['quantity']-left}
        for profile,cash in arm['cash'].items():
            ps=[p for p in arm['positions'].values() if p['profile']==profile]
            if any(not p.get('last_mark') or p['last_mark']['net_pnl'] is None for p in ps):continue
            equity=cash+sum(p['cost']+p['last_mark']['net_pnl'] for p in ps)
            arm['peak'][profile]=max(500.,arm['peak'].get(profile,500.),equity)
            arm['maximum_drawdown'][profile]=max(arm['maximum_drawdown'].get(profile,0.),arm['peak'][profile]-equity)
            if arm['maximum_drawdown'][profile]>=50.:arm['suspended'][profile]=True
    # Only retain book baselines for tokens enrolled or in the current fresh set.
    # Never forget previously consumed active-token depth; absent tokens are not
    # cleared here because reappearance must not replenish an unchanged quote.
    return state


def settle(state, proof, now):
    """Caller has independently verified exact native proof; rebind each lot."""
    if proof.get('native_payout_verified') is not True or proof.get('verified') is not True:
        raise ValueError('native payout proof required')
    for arm in state['arms'].values():
        for lot, p in list(arm['positions'].items()):
            if any(proof.get(k) != p[k] for k in ('market_id', 'event_id', 'token_id', 'rules_sha256')):
                continue
            if not at(p['at']) < at(proof['resolved_at']) <= at(proof['available_at']) <= now:
                continue
            arm['closed'].append({'lot': lot, 'profile': p['profile'], 'strategy': p['strategy'], 'event_id': p['event_id'],
                'pnl': p['quantity']*proof['payout']-p['cost'], 'cost': p['cost'], 'quantity': p['quantity'],
                'at': now.isoformat(), 'native_settled': True, 'proof_sha256': digest(proof)})
            arm['cash'][p['profile']]=arm['cash'].get(p['profile'],500.)+p['quantity']*proof['payout']
            if arm['day']!=now.date().isoformat():arm['day']=now.date().isoformat();arm['loss_today']={}
            arm['loss_today'][p['profile']]=arm['loss_today'].get(p['profile'],0.)+p['quantity']*proof['payout']-p['cost']
            if arm['loss_today'][p['profile']]<=-25.:arm['suspended'][p['profile']]=True
            del arm['positions'][lot]


def report(state, now):
    out = {}
    for name, arm in state['arms'].items():
        closed = arm['closed']; positions = arm['positions'].values()
        marks = [p.get('last_mark') for p in positions]
        known = all(m and m['net_pnl'] is not None and 0 <= (now-at(m['at'])).total_seconds() <= 15 for m in marks)
        out[name] = {'cash_hypothetical_by_profile':arm['cash'], 'maximum_drawdown_by_profile':arm['maximum_drawdown'], 'suspended_profiles':arm['suspended'], 'closed_lots': len(closed), 'open_lots': len(arm['positions']),
            'modeled_exit_pnl': sum(c['pnl'] for c in closed if not c['native_settled']),
            'verified_settlement_pnl': sum(c['pnl'] for c in closed if c['native_settled']),
            'unrealized_net_pnl': sum(m['net_pnl'] for m in marks) if known else None,
            'unresolved_capital': sum(p['cost'] for p in arm['positions'].values()),
            'parent_events': len({e['event_id'] for e in state['entries'].values()}),
            'limitation': 'alternative exit experiment; unresolved holds have no settled result; no winner selection'}
    return {'policy': POLICY, 'entries': len(state['entries']), 'matched_fill_counts':state['fill_counts'], 'withheld_fills':state['withheld_fills'], 'withholding_reasons':state['withholding_reasons'], 'arms': out, 'checkpoint_reached': any(n>=POLICY['max_entries'] for n in state['fill_counts'].values())}


def binding(market):
    return digest({k:market[k] for k in ('market_id','event_id','token_id','resolution_rules','resolution_source','outcome','end_time','tick_size','min_order_size')})
