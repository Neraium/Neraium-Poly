"""Replay exact public native fee parameters; never equate fees to all-in cost."""
import json
import math
from datetime import timedelta

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

DOCS = 'https://docs.polymarket.com/trading/fees'


def _get(store, identity):
    value = store.get(identity)
    if value is None:raise ValueError('native_fee_original_evidence_missing')
    if isinstance(value, dict):return value
    import hashlib
    if hashlib.sha256(value[1].encode()).hexdigest() != value[2]:raise ValueError('native_fee_original_hash_mismatch')
    return json.loads(value[1])


def replay_fee(observation, store, *, token_id, as_of):
    """Read original FeeObservation and both official identity/curve responses.

    Exponent1, native fd.r coefficient; base_fee is NEVER a replacement. Receipt
    TTL300s is an observation validity policy, not exchange event-time evidence.
    Unknown settlement costs, rounding/fill fragmentation, slippage and adverse
    selection are explicit. This proof does not certify probability calibration.
    """
    now=at(as_of)
    try:
        if not isinstance(observation,dict):raise TypeError('native_fee_observation_unavailable')
        raw=_get(store,observation['evidence_id'])
        if raw.get('token_id')!=token_id or raw.get('source')!='https://clob.polymarket.com':raise ValueError('native_fee_token_identity_mismatch')
        if not at(raw['timestamp'])<=at(raw['available_at'])<=now or now-at(raw['available_at'])>timedelta(seconds=300):raise ValueError('native_fee_observation_outside_300s')
        refs=raw.get('raw_response_ids',[])
        if not isinstance(refs,list) or len(refs)!=2:raise ValueError('native_fee_two_original_responses_required')
        responses=[_get(store,k) for k in refs]
        receipts=raw.get('retrieval_ids',[])
        if receipts:
            if len(receipts)!=2:raise ValueError('native_fee_two_retrieval_receipts_required')
            for rid,ref,r in zip(receipts,refs,responses,strict=True):
                receipt=_get(store,rid)
                if (receipt.get('source')!='https://clob.polymarket.com' or receipt.get('raw_response_id')!=ref
                    or receipt.get('url')!=r['url'] or receipt.get('content_sha256')!=r['content_sha256']
                    or not at(r['available_at'])<=at(receipt['timestamp'])<=at(receipt['available_at'])<=at(raw['available_at'])
                    or now-at(receipt['available_at'])>timedelta(seconds=300)):
                    raise ValueError('native_fee_current_retrieval_receipt_mismatch')
        for r in responses:
            if (r.get('source')!='https://clob.polymarket.com' or digest(r['payload'])!=r['content_sha256']
                or not at(r['timestamp'])<=at(r['available_at'])<=at(raw['available_at'])
                or (not receipts and now-at(r['available_at'])>timedelta(seconds=300))):
                raise ValueError('native_fee_response_source_hash_or_availability_mismatch')
        parent,details=[r['payload'] for r in responses]
        condition=parent.get('condition_id')
        if (not isinstance(condition,str) or not condition
            or responses[0]['url']!='https://clob.polymarket.com/markets-by-token/'+token_id
            or responses[1]['url']!='https://clob.polymarket.com/clob-markets/'+condition
            or token_id not in {str(parent.get('primary_token_id')),str(parent.get('secondary_token_id'))}
            or details.get('c',condition)!=condition
            or token_id not in {str(t.get('t')) for t in details.get('t',[]) if isinstance(t,dict)}):raise ValueError('native_fee_market_membership_unverified')
        fd=details['fd'];rate=fd.get('r');exponent=fd.get('e')
        if (type(rate) not in (int,float) or not math.isfinite(rate) or not 0<=rate<=1
            or type(exponent) not in (int,float) or exponent!=1 or fd.get('to') is not True):raise ValueError('unsupported_native_fee_curve')
        if type(raw.get('fee_rate')) not in (int,float) or abs(raw['fee_rate']-rate)>1e-12:raise ValueError('native_fee_coefficient_bound_mismatch')
        return {'status':'verified_current_protocol_curve','token_id':token_id,'condition_id':condition,
            'rate':rate,'exponent':1,'taker_only':True,'formula':'shares * fd.r * price * (1-price)',
            'documentation':DOCS,'fee_observation_id':raw['id'],'fee_observation_sha256':digest(raw),
            'raw_response_ids':refs,'retrieval_ids':receipts,'available_at':raw['available_at'],'as_of':now.isoformat(),
            'source_timestamp':None,'timestamp_semantics':'public responses provide retrieval/availability time; exchange effective-time unavailable',
            'rounding':'official nearest 5 decimals; per-fill count unknown, conservative bound used',
            'all_in_costs_verified':False,'missing_cost_evidence':['fill_fragmentation_rounding','additional_slippage','latency_adverse_selection','capital_lockup_cost','settlement_redemption_cost'],
            'calibration_verified':False,'research_only':True,'trading_authority':False}
    except (ValueError,TypeError,KeyError,IndexError,OverflowError) as e:
        return {'status':'unavailable','reason':str(e)[:160],'all_in_costs_verified':False,'research_only':True,'trading_authority':False}


def level_fees(book, proof, *, fraction=.1, consumed_quantities=None):
    """USD amounts at surviving displayed depth; not fills or guaranteed fees."""
    if proof.get('status')!='verified_current_protocol_curve' or proof.get('token_id')!=book.token_id:return None
    if type(fraction) not in (int,float) or not 0<fraction<=1:raise ValueError('bounded_fee_participation_required')
    rate=proof['rate'];rows=[]
    for level in book.asks:
        if consumed_quantities is not None and level.price not in consumed_quantities:continue
        quantity=level.size*fraction
        if consumed_quantities is not None:quantity=min(quantity,consumed_quantities[level.price])
        fee=rate*level.price*(1-level.price)
        rows.append({'price':level.price,'displayed_quantity':level.size,'participating_quantity':quantity,
            'formula_fee_per_share':fee,'formula_fee_usd_before_rounding':quantity*fee,
            'conservative_entry_fee_per_share_bound':level.price*rate+.00001,
            'bound_assumption':'at most one rounded fee charge per acquired share; sub-share fill fragmentation unbounded'})
    return {'levels':rows,'rounding_fragmentation_verified':False,'all_in_costs_verified':False,
            'total_formula_fee_usd_before_rounding':math.fsum(r['formula_fee_usd_before_rounding'] for r in rows),
            'research_only':True,'actual_fill':False}


class ResearchFeeCache:
    """Bounded sidecar of exact public observations; does not change paper fees."""
    def __init__(self, store, adapter, *, clock, can_write):
        self.store,self.adapter,self.clock,self.can_write=store,adapter,clock,can_write
        self.observations={};self.attempts={};self.errors={}

    async def refresh(self, frame, *, forecast_tokens):
        now=at(self.clock());tokens=set(forecast_tokens);markets={m.token_id:m for m in frame.markets}
        eligible=[]
        for b in frame.books:
            m=markets.get(b.token_id)
            if (b.token_id in tokens and m is not None and m.market_id==b.market_id
                and m.status=='active' and m.end_time is not None and m.end_time>now
                and 0<=(now-b.timestamp).total_seconds()<=15 and 0<=(now-b.available_at).total_seconds()<=15
                and b.bids and b.asks):eligible.append(b.token_id)
        keep=set(sorted(set(eligible))[:32])
        self.observations={t:v for t,v in self.observations.items() if t in keep}
        self.attempts={t:v for t,v in self.attempts.items() if t in keep};self.errors={t:v for t,v in self.errors.items() if t in keep}
        for token in sorted(keep,key=lambda t:self.attempts.get(t,now-timedelta(days=1)))[:2]:
            if not self.can_write():return
            prior=self.attempts.get(token)
            if prior is not None and now-prior<timedelta(seconds=60):continue
            cached=self.observations.get(token)
            if cached and now-at(cached['observed_at'])<timedelta(seconds=240):continue
            self.attempts[token]=now
            try:
                raw=await self.adapter.observed_fee(token)
                if raw is not None:self.observations[token]=raw;self.errors.pop(token,None)
                else:self.errors[token]='native_curve_unavailable'
            except Exception as e:  # noqa: BLE001 - no unknown fee becomes zero
                self.errors[token]=type(e).__name__

    def proofs(self, *, as_of):
        return {t:replay_fee(v,self.store,token_id=t,as_of=as_of) for t,v in tuple(self.observations.items())}

    def status(self):
        return {'tokens':len(self.observations),'maximum_tokens':32,'requests_per_cycle_max':4,
            'errors':dict(self.errors),'all_in_costs_verified':False,'trading_authority':False}
