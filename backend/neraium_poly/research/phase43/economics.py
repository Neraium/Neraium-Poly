"""Accounting identities only: price losses do not prove probability-model error."""
from collections import defaultdict


def ledger(events, state=None):
    """Incrementally attribute actual modeled exits to allocated entry costs.

    Original event books and amounts remain authority. No missing outcome,
    queue-position or counterfactual price is invented. Amounts are USD.
    """
    state = state or {'trades': {}, 'unmatched_exits': 0}
    for e in events:
        key = e.get('profile', '') + '|' + e.get('order_id', '')
        if e['type'] == 'shadow_intent':
            c = e['candidate']
            state['trades'].setdefault(key, {
                'profile': e['profile'], 'order_id': e['order_id'], 'strategy': c['strategy'],
                'market_id': c['market']['market_id'], 'event_id': c['market']['event_id'],
                'question': c['market']['question'], 'forecast_id': c.get('forecast', {}).get('id'),
                'probability': c.get('probability'), 'uncertainty': c.get('uncertainty'),
                'fee_verified': e['fee_verified'], 'quantity': 0., 'entry_cost': 0.,
                'entry_principal': 0., 'entry_fees': 0., 'exit_quantity': 0.,
                'remaining_quantity':0., 'remaining_principal':0., 'remaining_entry_fees':0., 'allocated_entry_principal':0., 'allocated_entry_fees':0.,
                'exit_principal': 0., 'exit_fees': 0., 'allocated_entry_cost': 0.,
                'modeled_exit_pnl': 0., 'native_settlement_pnl': 0.,
                'entry_best_bid': c['book']['bids'][0]['price'],
                'entry_best_ask': c['book']['asks'][0]['price'],
            })
        elif e['type'] in ('modeled_fill', 'modeled_exit'):
            t = state['trades'].get(key)
            if t is None:
                state['unmatched_exits'] += 1
                continue
            principal = sum(v['price'] * v['quantity'] for v in e['levels'])
            fees = sum(v['fee'] for v in e['levels'])
            if e['type'] == 'modeled_fill':
                t['quantity'] += e['quantity']; t['entry_cost'] += e['cost']
                t['entry_principal'] += principal; t['entry_fees'] += fees
                t['remaining_quantity']+=e['quantity'];t['remaining_principal']+=principal;t['remaining_entry_fees']+=fees
            else:
                q=sum(v['quantity'] for v in e['levels'])
                if q>t['remaining_quantity']+1e-8:raise ValueError('exit exceeds attributed filled quantity')
                fraction=q/t['remaining_quantity']
                allocated_principal=t['remaining_principal']*fraction;allocated_fees=t['remaining_entry_fees']*fraction
                t['remaining_quantity']-=q;t['remaining_principal']-=allocated_principal;t['remaining_entry_fees']-=allocated_fees
                t['allocated_entry_principal']+=allocated_principal;t['allocated_entry_fees']+=allocated_fees
                t['exit_quantity'] += q
                t['exit_principal'] += principal; t['exit_fees'] += fees
                t['allocated_entry_cost'] += e['cost']; t['modeled_exit_pnl'] += e['pnl']
        # Native settlements have separate proof-ledger authority; never infer
        # them from a bid exit or guess an order ID missing in old records.
    return state


def attribution(state):
    totals = defaultdict(lambda: defaultdict(float))
    trades = []
    for t in state['trades'].values():
        if not t['quantity']:
            continue
        principal = t['allocated_entry_principal']
        entry_fee = t['allocated_entry_fees']
        reserve = t['allocated_entry_cost'] - principal - entry_fee
        exit_reserve = t['exit_principal'] - t['exit_fees'] - t['allocated_entry_cost'] - t['modeled_exit_pnl']
        # Frozen-entry spread versus subsequent bid movement is a diagnostic,
        # not an estimate of causal adverse selection or forecast accuracy.
        spread = t['exit_quantity'] * (t['entry_best_bid'] - t['entry_best_ask'])
        row = {**t, 'gross_price_pnl': t['exit_principal'] - principal,
               'allocated_entry_fees': entry_fee, 'entry_reserve': reserve,
               'exit_slippage': exit_reserve, 'entry_spread_diagnostic': spread,
               'probability_error': None, 'exit_reason': 'legacy trigger not recorded'}
        trades.append(row)
        for k in ('modeled_exit_pnl', 'gross_price_pnl', 'allocated_entry_fees', 'exit_fees', 'entry_reserve', 'exit_slippage'):
            totals[t['profile'] + '/' + t['strategy']][k] += row[k]
    return {'trades': trades, 'by_strategy': dict(totals), 'unmatched_exits': state['unmatched_exits'],
            'limitation': 'USD accounting decomposition; unresolved outcomes cannot attribute probability error; no causal adverse-selection attribution; legacy trigger unrecorded'}
