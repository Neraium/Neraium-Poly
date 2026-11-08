"""Finite-book research profit frontiers. No order, fill, or trading authority."""
import math

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

CAPITALS = (500, 1000, 10000, 100000, 1000000)
EPS = 1e-9


def _number(value, low=0, high=float('inf')):
    return type(value) in (float, int) and math.isfinite(value) and low <= value <= high


def analyze_depth(book, *, as_of, expected_payout, lower_payout=None, upper_payout=None,
                  fee_rate=None, slippage_per_share=0.0, latency_liquidity_fraction=0.1,
                  capitals=CAPITALS, max_capital=None, fee_per_share=None,
                  settlement_cost_per_share=None):
    """Optimize BUY prefixes by USD profit; any positive marginal edge is eligible.

    ``fee_rate`` is a caller-supplied effective acquisition surcharge scenario or
    conservative bound, NEVER an automatically interpreted exchange base fee.
    Alternatively supply an absolute ``fee_per_share``. The caller must establish
    that a bound covers every consumed level. Settlement/redemption costs are a
    separate nullable provision; unknown costs never silently become known zero.
    Spread crossing is already paid through ask prices. Sweep impact is VWAP
    minus best ask; additive slippage is an explicit extra conservative reserve.
    All sizing is continuous hypothetical shares, not exchange-authorized lots.
    """
    result = {'schema_version': 'phase28-depth-profit-v1', 'status': 'withheld', 'reasons': [],
              'per_level': [], 'scenarios': [], 'maximum_supported_quantity': None,
              'maximum_supported': None, 'maximum_gross_profit': None,
              'maximum_point_profit': None, 'maximum_conservative_profit': None,
              'maximum_conservative_positive_net_profit': None,
              'research_only': True, 'trading_authority': False, 'certification_authority': False,
              'actual_fill': False, 'evidence_verified': False, 'cash_alternative_net_profit': 0.,
              'realized_profit': None}
    try:
        if (not _number(expected_payout, 0, 1)
            or lower_payout is not None and not _number(lower_payout, 0, expected_payout)
            or upper_payout is not None and not _number(upper_payout, expected_payout, 1)):
            raise ValueError('finite_consistent_payout_assumptions_required')
        if (fee_rate is not None and not _number(fee_rate, 0, 1)
            or fee_per_share is not None and not _number(fee_per_share, 0, 1)
            or fee_rate is not None and fee_per_share is not None
            or settlement_cost_per_share is not None and not _number(settlement_cost_per_share, 0, 1)
            or not _number(slippage_per_share, 0, 1)
            or not _number(latency_liquidity_fraction, 0, 1)
            or max_capital is not None and not _number(max_capital, EPS, 1e12)):
            raise ValueError('finite_nonnegative_unambiguous_cost_and_capacity_assumptions_required')
        if (not isinstance(capitals, (list, tuple)) or not 1 <= len(capitals) <= 16
            or any(not _number(x, EPS, 1e12) for x in capitals) or len(set(capitals)) != len(capitals)):
            raise ValueError('bounded_distinct_hypothetical_capitals_required')
        if isinstance(book, dict):
            if any(not isinstance(book.get(side), (list, tuple)) for side in ('bids', 'asks')):
                raise ValueError('explicit_two_sided_book_required')
            if sum(len(book[s]) for s in ('bids', 'asks')) > 4096:
                raise ValueError('bounded_complete_book_levels_required')
        b = book if isinstance(book, OrderBookSnapshot) else OrderBookSnapshot.model_validate(book)
        if (len(b.bids)+len(b.asks) > 4096
            or len({x.price for x in b.bids}) != len(b.bids)
            or len({x.price for x in b.asks}) != len(b.asks)
            or any(not 1 <= len(x) <= 512 for x in (b.id, b.market_id, b.token_id))):
            raise ValueError('bounded_unique_book_identity_and_levels_required')
        if any(not _number(x.size, EPS, 1e12) for x in (*b.bids, *b.asks)) or not _number(math.fsum(x.size for x in b.asks), 0, 1e12):
            raise ValueError('bounded_finite_displayed_quantity_required')
        now = at(as_of)
        health = assess_book(b, now, max_spread=1)
        if (not health.healthy or b.exchange != 'polymarket' or b.source not in PUBLIC_BOOK_SOURCES
            or not 0 <= (now-b.available_at).total_seconds() <= 15):
            raise ValueError('fresh_authentic_complete_two_sided_depth_required')
        fee_known = fee_rate is not None or fee_per_share is not None
        all_costs_known = fee_known and settlement_cost_per_share is not None
        provision = settlement_cost_per_share or 0.
        share_slippage = float(slippage_per_share)
        fraction = float(latency_liquidity_fraction)

        def entry_fee(price):
            return price*fee_rate if fee_rate is not None else fee_per_share or 0.

        def summarize(quantity, principal, fees, slippage, settlement):
            known_cost = principal+fees+slippage+settlement
            gross = expected_payout*quantity-principal
            net = gross-fees-slippage-settlement if all_costs_known else None
            lower = lower_payout*quantity-known_cost if all_costs_known and lower_payout is not None else None
            upper = upper_payout*quantity-known_cost if all_costs_known and upper_payout is not None else None
            return {'quantity': quantity, 'principal': principal, 'entry_fees': fees if fee_known else None,
                    'slippage_cost': slippage, 'settlement_cost': settlement if settlement_cost_per_share is not None else None,
                    'acquisition_capital': principal+fees+slippage if fee_known else None,
                    'capital_required': known_cost if all_costs_known else None,
                    'known_capital_lower_bound': known_cost, 'expected_gross_profit': gross,
                    'entry_cost_only_net_profit': gross-fees-slippage if fee_known else None,
                    'expected_net_profit': net, 'lower_net_profit': lower, 'upper_net_profit': upper,
                    'net_profit_interval': [lower, upper] if lower is not None and upper is not None else None,
                    'return_on_capital': net/known_cost if net is not None and known_cost > EPS else None,
                    'lower_return_on_capital': lower/known_cost if lower is not None and known_cost > EPS else None,
                    'entry_vwap': principal/quantity if quantity > EPS else None,
                    'sweep_impact_per_share': principal/quantity-b.asks[0].price if quantity > EPS else None}

        def walk(budget=None, objective=None, trace=False):
            q = principal = fees = slippage = settlement = 0.; rows = []; stopped = None
            for i, level in enumerate(b.asks):
                fee = entry_fee(level.price)
                cost = level.price+fee+share_slippage+provision
                marginal = None
                if objective == 'gross':marginal = expected_payout-level.price
                elif objective == 'point':marginal = expected_payout-cost
                elif objective == 'lower':marginal = lower_payout-cost
                if marginal is not None and marginal <= 0:
                    stopped = 'nonpositive_marginal_profit';break
                available = level.size*fraction
                remaining = max(0., budget-(principal+fees+slippage+settlement)) if budget is not None else float('inf')
                take = min(available, remaining/cost)
                if take <= EPS:
                    if available > EPS and budget is not None:stopped = 'capital_budget_exhausted';break
                    continue
                q += take;principal += take*level.price;fees += take*fee
                slippage += take*share_slippage;settlement += take*provision
                if trace:
                    rows.append({'level_index': i, 'price': level.price, 'displayed_quantity': level.size,
                                 'participating_quantity': available, 'consumed_quantity': take,
                                 'marginal_point_net_profit_per_share': expected_payout-cost if all_costs_known else None,
                                 'marginal_lower_net_profit_per_share': lower_payout-cost if all_costs_known and lower_payout is not None else None,
                                 'cumulative': summarize(q, principal, fees, slippage, settlement)})
                if budget is not None and principal+fees+slippage+settlement >= budget-EPS:
                    stopped = 'capital_budget_exhausted';break
            row = summarize(q, principal, fees, slippage, settlement)
            row.update(stopping_reason=stopped or 'participating_depth_exhausted',
                       participating_depth_exhausted=stopped is None,
                       cost_complete=all_costs_known, actual_fill=False)
            return row, rows

        maximum, levels = walk(max_capital, trace=True)
        point = walk(max_capital, 'point')[0] if all_costs_known else None
        conservative = walk(max_capital, 'lower')[0] if all_costs_known and lower_payout is not None else None
        gross_max = walk(max_capital, 'gross')[0]
        result.update(status='conditional_assumption_scenarios', book_id=b.id,
            book_sha256=digest(b.model_dump(mode='json')), market_id=b.market_id, token_id=b.token_id,
            source=b.source, source_timestamp=b.timestamp.isoformat(), receipt_timestamp=b.available_at.isoformat(),
            evaluated_at=now.isoformat(), expected_payout=expected_payout, lower_payout=lower_payout, upper_payout=upper_payout,
            spread=b.asks[0].price-b.bids[0].price, best_ask=b.asks[0].price, best_bid=b.bids[0].price,
            displayed_ask_quantity=sum(x.size for x in b.asks), displayed_ask_notional=sum(x.price*x.size for x in b.asks),
            participating_ask_quantity=sum(x.size*fraction for x in b.asks),
            maximum_supported_quantity=maximum['quantity'], maximum_supported=maximum, maximum_gross_profit=gross_max,
            maximum_point_profit=point, maximum_conservative_profit=conservative,
            maximum_conservative_positive_net_profit=max(0., conservative['lower_net_profit']) if conservative is not None else None,
            per_level=levels, assumptions={'fee_rate': fee_rate, 'fee_per_share': fee_per_share,
                'fee_convention': 'caller-supplied effective acquisition surcharge scenario/bound, not native exchange base fee',
                'settlement_cost_per_share': settlement_cost_per_share, 'slippage_per_share': slippage_per_share,
                'latency_liquidity_fraction': fraction, 'fee_evidence_verified': False,
                'calibration_verified': False, 'settlement_costs_verified': False,
                'cost_complete': all_costs_known, 'max_capital': max_capital,
                'capital_budget_scope': 'hypothetical full provided capital; caller must apply concentration/reservation controls',
                'quantity_scope': 'continuous shares; minimum order/lot rules require independent verification'},
            capital_lockup_seconds=None, settlement_duration_verified=False, future_exit_liquidity_verified=False)
        for capital in capitals:
            budget = min(capital, max_capital) if max_capital is not None else capital
            supported = walk(budget)[0]
            p = walk(budget, 'point')[0] if all_costs_known else None
            lower = walk(budget, 'lower')[0] if all_costs_known and lower_payout is not None else None
            result['scenarios'].append({'hypothetical_bankroll': capital, 'capital_budget': budget,
                'supported': supported, 'maximum_point_profit': p, 'maximum_conservative_profit': lower,
                'maximum_gross_profit': walk(budget, 'gross')[0],
                'capital_utilization': supported['capital_required']/capital if all_costs_known else None,
                'partial_capacity': supported['stopping_reason'] == 'participating_depth_exhausted',
                'accounts_created': 0, 'actual_fill': False})
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        result['reasons'] = [str(error)[:160]]
    result['limitations'] = ['Supplied payout/cost bounds are research assumptions, not independently verified edge or calibration',
        'Displayed liquidity and an assumed latency haircut do not prove a future fill or queue priority',
        'Ask prices already include spread crossing; sweep impact is not an additional duplicate cost',
        'Unknown entry or settlement costs produce null full net profit and ROI',
        'No future liquidity replenishment, price improvement, leverage, or proportional capital scaling assumed',
        'Resolution disputes, lockup duration, portfolio correlation and lot-size approval must be supplied by caller',
        'No new accounts, orders, positions, realized profit or execution authority are created']
    return result
