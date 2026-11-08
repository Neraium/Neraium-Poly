"""Replay-bound weather economic sensitivities, never unconditional profit proof.

Weather challengers model a completion-conditioned reference outcome. Neither
model disagreement nor a verified taker curve establishes calibrated native
payout probabilities. This diagnostic makes the missing margin explicit.
"""
import math
from pathlib import Path

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase28.execution import analyze_depth
from neraium_poly.research.phase29.costs import replay_fee
from neraium_poly.research.phase32.weather import _mapping


def weather_economic_diagnostic(forecast, evidence, *, as_of, fee_observation=None, store=None):
    """Reconstruct ORIGINAL quote economics; later observations cannot repair it.

    Formula fees are deducted only after replay of original native responses
    available by the forecast timestamp. Total net profit remains unknown: fill
    fragmentation, adverse selection, settlement and conditional target risk
    are not silently assigned zero. A stale original is historical analysis,
    never a fresh execution candidate. Work is bounded by the model and book.
    """
    now=at(as_of)
    out={'schema_version':'phase34-weather-economic-sensitivity-v1','as_of':now.isoformat(),
         'implementation_sha256':digest(Path(__file__).read_text()),'status':'withheld',
         'rejections':[],'conservative_expected_net_profit':None,'qualified_opportunity':False,
         'actual_fill':False,'realized_pnl':None,'research_only':True,'trading_authority':False,
         'certification_authority':False,'market_baseline_superiority':None}
    try:
        if not isinstance(forecast,dict) or not isinstance(evidence,(list,tuple)) or len(evidence)>64:
            raise ValueError('bounded_original_weather_evidence_required')
        f=forecast;module,c,end,_source_end,_url=_mapping(f)
        if module.replay(f,evidence,as_of=now).get('verified') is not True:
            raise ValueError('original_weather_model_and_book_replay_required')
        created=at(f['timestamp']);b=OrderBookSnapshot.model_validate(f['book'])
        depth=analyze_depth(b,as_of=created,expected_payout=f['probability'],
            lower_payout=f['lower_probability'],upper_payout=f['upper_probability'])
        if depth['status']=='withheld':raise ValueError('original_weather_depth_required')
        chosen=depth['maximum_gross_profit'];q=chosen['quantity'];principal=chosen['principal']
        proof=(replay_fee(fee_observation,store,token_id=f['token_id'],as_of=created)
               if fee_observation is not None and store is not None else
               {'status':'unavailable','reason':'causal_original_native_fee_evidence_missing'})
        curve_fee=None;consumed=[]
        if proof['status']=='verified_current_protocol_curve':
            remaining=q
            for p in b.asks:
                take=min(remaining,p.size*.1)
                if take>1e-12:consumed.append({'price':p.price,'quantity':take,'formula_fee':take*proof['rate']*p.price*(1-p.price)})
                remaining-=take
                if remaining<=1e-9:break
            if remaining>1e-8:raise ValueError('original_depth_quantity_not_recoverable')
            curve_fee=math.fsum(p['formula_fee'] for p in consumed)
        fee_floor=curve_fee if curve_fee is not None else 0.
        failures=['uncalibrated_probability_interval','conditional_reference_is_not_native_payout',
                  'all_in_costs_and_native_settlement_not_verified']
        if f['lower_probability']*q-principal-fee_floor<=0:failures.append('uncertainty_lower_bound_does_not_cover_acquisition')
        if proof['status']!='verified_current_protocol_curve':failures.append('causal_original_native_fee_evidence_missing')
        live_age=(now-b.timestamp).total_seconds();receipt_age=(now-b.available_at).total_seconds()
        if not 0<=live_age<=15 or not 0<=receipt_age<=15:failures.append('original_book_not_current_executable_liquidity')
        if now>=end:failures.append('original_weather_event_ended')
        out.update(status='original_quote_research_sensitivity',forecast_id=f.get('id') or digest(f),
            forecast_sha256=digest(f),model_id=f['model_id'],model_version=f['model_version'],
            market_id=f['market_id'],event_id=f['event_id'],token_id=f['token_id'],rules_sha256=f['rules_sha256'],
            station=c['station'],station_local_day=c['day'],event_group_id=digest(['AWC-station-local-day',c['station'],c['day']]),
            forecast_timestamp=f['timestamp'],evidence_cutoff=f['evidence_cutoff'],event_end_time=f['event_end_time'],
            book_id=b.id,book_sha256=digest(b.model_dump(mode='json')),book_timestamp=b.timestamp.isoformat(),book_receipt_timestamp=b.available_at.isoformat(),
            original_point_probability=f['probability'],original_probability_interval=[f['lower_probability'],f['upper_probability']],
            interval_status='model_policy_envelope_not_fitted_confidence_interval',
            contemporaneous_market_midpoint=f['market_expected_payout'],market_probability_comparable=False,
            point_gross_optimal_quantity=q,point_gross_optimal_principal=principal,
            point_expected_gross_profit=chosen['expected_gross_profit'],
            lower_expected_gross_profit_at_same_quantity=f['lower_probability']*q-principal,
            upper_expected_gross_profit_at_same_quantity=f['upper_probability']*q-principal,
            original_quantity_book_levels=consumed,causal_native_fee_proof=proof,
            unrounded_native_formula_fee=curve_fee,
            conditional_point_profit_after_formula_fee=(chosen['expected_gross_profit']-curve_fee if curve_fee is not None else None),
            known_acquisition_cost_lower_bound=principal+fee_floor,
            break_even_probability_before_unknown_costs=(principal+fee_floor)/q if q>1e-12 else None,
            point_probability_headroom_before_unknown_costs=(f['probability']-(principal+fee_floor)/q if q>1e-12 else None),
            maximum_unknown_cost_budget_at_point=(chosen['expected_gross_profit']-curve_fee if curve_fee is not None else None),
            source_lineages=list(f.get('source_lineages',[])),
            assumptions={'latency_liquidity_fraction':.1,'fee':'verified unrounded native curve only; rounding/fragmentation not verified',
                         'probability':'original conditional reference estimate; not independent native payout probability',
                         'execution':'hypothetical contemporaneous displayed ask prefixes, no actual or guaranteed fill'},
            rejections=failures)
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,OSError) as error:
        out.update(status='withheld',rejections=[str(error)[:180]])
    return out
