"""Declared cost stress scenarios; estimates never certify all-in costs."""
from neraium_poly.research.phase28.execution import analyze_depth

CASES=(('low_cost_assumption',0.,0.,0.),('buffered_assumption',.05,.005,.001),('stressed_assumption',.10,.02,.01))


def cost_sensitivity(book,*,as_of,probability,lower=None,upper=None,native_fee=None):
    rows=[];known=isinstance(native_fee,dict) and native_fee.get('status')=='verified_current_protocol_curve' and native_fee.get('token_id')==book.token_id
    for name,fallback,slippage,settlement in CASES:
        rate=native_fee['rate'] if known else fallback
        r=analyze_depth(book,as_of=as_of,expected_payout=probability,lower_payout=lower,upper_payout=upper,
            fee_rate=rate,slippage_per_share=slippage,settlement_cost_per_share=settlement)
        point=r.get('maximum_point_profit');worst=r.get('maximum_conservative_profit')
        def scalar(x):
            if not isinstance(x,dict):return None
            return {k:x.get(k) for k in ['quantity','principal','entry_fees','slippage_cost','settlement_cost','capital_required','entry_vwap',
                'expected_gross_profit','expected_net_profit','lower_net_profit','return_on_capital','stopping_reason']}
        rows.append({'name':name,'protocol_curve_source_verified':known,'effective_fee_surcharge_bound':rate,
            'fee_assumption':None if known else 'explicit illustrative acquisition surcharge; not native verified fees',
            'extra_slippage_and_adverse_selection_per_share':slippage,'assumed_settlement_redemption_cost_per_share':settlement,
            'unverified_rounding_fragmentation':True,'participating_fraction':.1,
            'maximum_point_estimate':scalar(point),'maximum_lower_bound_estimate':scalar(worst),
            'hypothetical_capital_scenarios':[{'hypothetical_bankroll':x['hypothetical_bankroll'],'maximum_point_estimate':scalar(x['maximum_point_profit']),'maximum_lower_bound_estimate':scalar(x['maximum_conservative_profit']),'accounts_created':0} for x in r.get('scenarios',[])],
            'all_in_costs_verified':False,'qualified_opportunity':False,'actual_fill':False})
    return {'scope':'point-in-time model estimates under declared assumed extra costs; not verified expected profit or actual fills',
        'cases':rows,'calibration_verified':False,'all_in_costs_verified':False,'execution_authorized':False,'research_only':True}
