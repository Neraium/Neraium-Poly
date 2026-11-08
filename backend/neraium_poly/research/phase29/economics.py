"""Independent observation stages even when a forecast is too old to admit."""
import math

from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase28.execution import analyze_depth
from neraium_poly.research.phase29.costs import level_fees


def diagnostic(forecast, market, book, row, *, as_of, native_fee=None):
    now=at(as_of);age=(now-at(forecast['timestamp'])).total_seconds()
    fresh=0<=age<=300
    result={'identity_validated':row['settlement_risk']['rules_match_current_market'],
        'forecast_fresh_for_admission':fresh,'forecast_age_seconds':age,
        'book_matched':bool(book and book.market_id==forecast['market_id'] and book.token_id==forecast['token_id']),
        'book_executable':row['book_qualified_for_current_observation'],
        'probability_semantics':forecast.get('probability_semantics'),'economic_evaluation_completed':False,
        'hypothesis_sensitivity':None,'current_forecast_expected_profit':None,
        'native_fee':native_fee or {'status':'unavailable','reason':'native_fee_observation_unavailable','all_in_costs_verified':False},
        'cost_completeness':'unknown_all_in_costs','research_only':True,'trading_authority':False}
    if not result['identity_validated'] or not result['book_matched'] or not result['book_executable']:return result
    if (market is None or market.status!='active' or market.end_time is None or market.end_time<=now
        or at(forecast['event_end_time'])<=now):return result
    value=row.get('expected_payout')
    if value is None and forecast.get('probability_semantics')=='binary_event_probability':value=forecast.get('probability')
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:return result
    # This sensitivity reuses the ORIGINAL probability. It is never promoted to a
    # new forecast, and never supplies qualification or shadow-admission values.
    analysis=analyze_depth(book,as_of=now,expected_payout=value,max_capital=5)
    if analysis['status']=='withheld':return result
    probe=analysis.get('maximum_supported');fee_evidence=level_fees(book,result['native_fee'],consumed_quantities={r['price']:r['consumed_quantity'] for r in analysis['per_level']})
    fee_amount=None
    if fee_evidence is not None:
        rate=result['native_fee']['rate']
        fee_amount=math.fsum(x['consumed_quantity']*rate*x['price']*(1-x['price']) for x in analysis['per_level'])
    sensitivity=None
    if fresh:
        from neraium_poly.research.phase30.sensitivity import cost_sensitivity
        lo,hi=forecast.get('lower_probability'),forecast.get('upper_probability')
        valid=type(lo) in (int,float) and type(hi) in (int,float) and 0<=lo<=value<=hi<=1
        sensitivity=cost_sensitivity(book,as_of=now,probability=value,lower=lo if valid else None,upper=hi if valid else None,native_fee=result['native_fee'])
    result.update(economic_evaluation_completed=True,cost_sensitivity=sensitivity,hypothesis_sensitivity={
        'scope':'original_forecast_current_book_counterfactual' if not fresh else 'unvalidated_current_forecast_scenario',
        'original_forecast_timestamp':forecast['timestamp'],'evaluation_at':now.isoformat(),
        'forecast_reissued':False,'forecast_time_current':fresh,'forecast_admissible':False,
        'depth_analysis':analysis,'native_fee_per_level':fee_evidence,
        'probe_entry_formula_fee_usd_before_rounding':fee_amount,
        'probe_gross_less_formula_entry_fee_usd':probe['expected_gross_profit']-fee_amount if probe and fee_amount is not None else None,
        'not_after_all_costs':True,'net_expected_profit':None,'verified_profitability':False})
    return result


def stage_counts(rows):
    keys=('identity_validated','book_matched','book_executable','economic_evaluation_completed')
    return {k:sum(bool(r.get('pipeline',{}).get(k)) for r in rows) for k in keys}
