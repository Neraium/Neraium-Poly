"""Decision-time economic diagnostics; estimates never confer execution authority."""
from neraium_poly.research.phase24.continuous import at


def evaluate(candidates,profiles,now):
    rows=[]
    for c in candidates[:128]:
        b=c['book'];m=c['market'];ask=b['asks'][0]['price'];bid=b['bids'][0]['price']
        for name,config in profiles.items():
            fee=c.get('decision_fee',{});known=fee.get('status')=='verified_current_protocol_curve' and fee.get('token_id')==c['token_id'] and 0<=(now-at(fee['as_of'])).total_seconds()<=300
            rate=fee.get('rate') if known else config['unknown_fee'];target=c['target']
            if c['probability'] is not None:target=target*(1-config['haircut'])+c.get('forecast',{}).get('lower_probability',0)*config['haircut']
            reasons=[];q=capital=gross=costs=0.
            if rate is None:reasons.append('native_fee_unavailable')
            else:
                budget=config['size'];limit=c.get('limit',ask)
                for level in b['asks'][:8]:
                    price=level['price']
                    if price>limit+1e-9:break
                    per=price+rate*price*(1-price)+.002
                    exit_cost=rate*target*(1-target)+.0015 if c['probability'] is None else 0.
                    if target-per-exit_cost<=config['edge']+1e-9:break
                    size=min(level['size']*.1,max(0.,budget-capital)/per)
                    q+=size;capital+=size*per;gross+=size*(target-price);costs+=size*(per-price+exit_cost)
                if q<=1e-9:reasons.append('nonpositive_after_cost_edge_at_executable_ask')
                elif q+1e-9<m['min_order_size']:reasons.append('native_minimum_quantity_not_supported_by_budget_and_depth')
            if ask-bid>config['spread']:reasons.append('profile_spread')
            if name=='conservative' and c.get('forecast',{}).get('calibration_status') not in ('qualified','calibrated'):reasons.append('conservative_calibration_withheld')
            rows.append({'strategy':c['strategy'],'profile':name,'market_id':m['market_id'],'event_id':m['event_id'],'token_id':c['token_id'],'question':m['question'],
                'decision_at':now.isoformat(),'book_id':b['id'],'book_at':b['timestamp'],'bid':bid,'ask':ask,'levels':b['asks'][:8],
                'model_probability':c['probability'],'pricing_target':target,'uncertainty':c.get('uncertainty'),'evidence_kind':c['evidence_kind'],
                'estimated_quantity':q,'capital':capital,'estimated_gross_profit':gross,'estimated_execution_costs':costs,'estimated_net_profit':gross-costs,
                'uncertainty_lower_net_profit':q*c.get('forecast',{}).get('lower_probability',0)-capital if c['probability'] is not None else None,
                'settlement_end':m.get('end_time'),'correlation_group':m['event_id'],
                'return_on_capital':(gross-costs)/capital if capital else None,'maximum_principal_loss':capital,'native_fee_verified':known,'fee_rate_assumption':rate,
                'modeled_reserves_per_share':.002,'additional_exit_slippage_per_share':.0015 if c['probability'] is None else 0.,
                'all_in_costs_verified':False,'entry_diagnostics':reasons,'status':'unvalidated_hypothesis_only','actual_fill':False,'trading_authority':False,
                'limitation':'best-ask-limit intent, bounded10% participation; later book required; portfolio, native size, shared-depth and risk gates apply independently; fees/slippage are not all verified costs'})
    return sorted(rows,key=lambda r:(bool(r['entry_diagnostics']),-r['estimated_net_profit']))[:64]
