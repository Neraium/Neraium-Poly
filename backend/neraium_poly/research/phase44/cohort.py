"""New frozen shadow cohort; prior portfolios/loss suspensions are never reset.

Three distinct hypotheses: external event probabilities held to settlement;
verified complementary-token payout consistency; executable BID trend with
round-trip costs (not midpoint extrapolation). No resting maker-fill model.
"""
import hashlib
from pathlib import Path
from typing import ClassVar

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase42.engine import StrategyCycle, StrategyEngine
from neraium_poly.research.phase42.strategies import propose

DEFINITIONS={
 'independent':{'thesis':'External source-replayed event probability versus acquisition cost; settle-aligned holding, not five-minute probability trading.','exit':'net probability-target repricing or20% risk stop; otherwise exact native settlement','horizon':86400,'scored_probability':True},
 'consistency':{'thesis':'Acquire exact same binary condition complementary tokens below unit payout after verified fees; partial-leg risk remains.','exit':'verified native payout only; never claim atomic arbitrage','horizon':86400,'scored_probability':False},
 'momentum':{'thesis':'Past executable BID appreciation with bid-depth support and verified round-trip costs; test persistence, not fair probability.','exit':'executable net target or60s timeout or20% risk stop','horizon':60,'scored_probability':False}}


class StrategyCycle44(StrategyCycle):
    pass


def opportunities(markets,books,forecasts,history,prior,fees,now):
    candidates,rejected=propose(markets,books,forecasts,history,prior,fees,now)
    candidates=[c for c in candidates if c['strategy'] in ('independent','consistency')]
    rejected=[r for r in rejected if r['strategy'] in ('independent','consistency')]
    for token,m in markets.items():
        b=books.get(token);h=history.get(token,[]);fee=fees.get(token,{})
        old=[v for v in h if 30<=(now-at(v['at'])).total_seconds()<=120 and 'bid' in v]
        if b is None or len(old)<3 or fee.get('status')!='verified_current_protocol_curve':
            rejected.append({'strategy':'momentum','token_id':token,'reason':'bid_history_and_verified_fees_required'});continue
        rate=fee['rate'];change=b.bids[0].price-old[0]['bid'];spread=b.asks[0].price-b.bids[0].price
        # Frozen price-persistence hypothesis; disclose variation rather than
        # misrepresenting a price target as an independent outcome probability.
        target=min(.999,b.bids[0].price+max(0.,change)*.5)
        friction=rate*b.asks[0].price*(1-b.asks[0].price)+rate*target*(1-target)+.0035
        if change<=0 or target<=b.asks[0].price+friction or sum(v.size*v.price for v in b.bids[:8])<50:
            rejected.append({'strategy':'momentum','token_id':token,'reason':'bid_trend_does_not_cover_round_trip_friction_and_depth'});continue
        candidates.append({'strategy':'momentum','token_id':token,'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),
            'created_at':now.isoformat(),'domain':'market_repricing','key':digest(['v44-bid-trend',token,old[0]['at'],b.id]),
            'target':target,'probability':None,'evidence_kind':'observed_executable_bid_path; no independent fair probability claim',
            'uncertainty':{'calibration':'unvalidated pricing hypothesis','past_bid_change':change,'spread':spread,'net_target_after_modeled_friction':target-b.asks[0].price-friction}})
    return candidates,rejected


class Cohort(StrategyEngine):
    record_type=StrategyCycle44
    identity_prefix='strategy44'
    source_name='neraium-poly/strategy-competition/v44'
    definitions=DEFINITIONS
    profile_configs:ClassVar[dict]={
        'aggressive':{'size':3.,'edge':0.,'spread':.15,'haircut':0.,'unknown_fee':.10},
        'balanced':{'size':3.,'edge':0.,'spread':.08,'haircut':.25,'unknown_fee':None},
        'conservative':{'size':3.,'edge':.01,'spread':.05,'haircut':1.,'unknown_fee':None}}
    proposer=staticmethod(opportunities)
    def extra_policy(self):
        return {**super().extra_policy(),'cohort':'phase44-friction-aware-v1','cohort_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'accounting':'new alternative shadow cohort only; original Phase41/42/43 cash, positions, suspensions and losses remain intact',
                'entry_review_checkpoint':'first100 distinct event groups; no automatic promotion or reset; original financial and certification gates unchanged'}


class LegacyCohort(StrategyEngine):
    """Original ledgers keep all positions, losses, stops and frozen exits."""
    entry_enrollment_open=False
