"""Independent, uncalibrated daily-barrier challengers; never order authority.

Gaussian first-passage and empirical OHLC block resampling are competing
assumptions on the SAME external source, not independent corroborating sources.
"""
import hashlib
import math
import random
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from statistics import NormalDist, stdev
from zoneinfo import ZoneInfo

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.finance import digest
from neraium_poly.research.phase18.forecasting import ASSETS, daily_low_rules, map_event_contract
from neraium_poly.research.phase18.sources import at, completed_minutes

MODELS = ('gaussian-first-passage-v23.1', 'empirical-ohlc-block-bootstrap-v23.1')
FEATURE_VERSION = 'causal-closed-minute-return-and-intrabar-low-v1'


def map_challenger_contract(market, *, now):
    """Add future local days of the unchanged exact daily-low rule, up to72h.

    Future windows require simulation/integration over the intervening period;
    a terminal-price contract is never silently converted into a barrier event.
    """
    now = at(now)
    m = MarketSnapshot.model_validate(market.model_dump() if isinstance(market, MarketSnapshot) else market)
    old = map_event_contract(m, now=now)
    if old.compatible and not old.review_required:
        return old
    match = re.fullmatch(r'Will (Bitcoin|Ethereum) dip to \$((?:\d{1,3}(?:,\d{3})+|\d+)) on ([A-Z][a-z]+ \d{1,2})\?', m.question)
    if not match or m.end_time is None:
        return old
    name, value, date = match.groups()
    asset, symbol = ASSETS[name]
    local_end = m.end_time.astimezone(ZoneInfo('America/New_York'))
    try:
        day = datetime.strptime(f'{(local_end-timedelta(days=1)).year} {date}', '%Y %B %d').replace(tzinfo=ZoneInfo('America/New_York'))
    except ValueError:
        return old
    if (m.exchange != 'polymarket' or m.source != 'https://gamma-api.polymarket.com'
        or max(m.timestamp, m.available_at) > now or m.status != 'active'
        or m.outcome not in {'Yes', 'No'} or not now < day or local_end != day+timedelta(days=1)
        or not 0 < (m.end_time-now).total_seconds() <= 72*3600
        or m.resolution_rules != daily_low_rules(name)
        or m.resolution_source != f'https://www.binance.com/en/trade/{asset}_USDT'):
        return old
    params = {'asset': asset, 'symbol': symbol, 'quote_currency': 'USDT',
        'threshold': float(value.replace(',', '')), 'operator': '<=', 'selected_outcome': m.outcome,
        'price_definition': 'final_minute_low', 'timezone': 'America/New_York',
        'period_start_utc': day.astimezone(UTC).isoformat(), 'period_end_utc': m.end_time.isoformat(),
        'candle_convention': 'all_UTC_1m_candles_with_open_in_half_open_local_day',
        'market_snapshot': m.model_dump(mode='json'), 'reference_source': m.resolution_source}
    if params['threshold'] <= 0:
        return old
    return DomainContract(id=digest(['phase23-exact-future-daily-low', m.id, params]), timestamp=now,
        available_at=now, source='neraium-poly/challenger-contract/v23', domain='crypto',
        event_id=m.event_id, market_id=m.market_id, token_id=m.token_id,
        contract_type='binance_daily_low_barrier', probability_semantics='binary_event_probability',
        rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(), parameters=params,
        compatible=True, review_required=False)


def _crypto_enrollment_definitions():
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    methods = [
        ('Gaussian zero-log-drift first passage, integrating uncertain future-day starting price',
         'Constant volatility, continuous first passage and no jumps; uncalibrated tails'),
        ('Stationary moving-block resampling of authentic joint close returns and intrabar lows',
         'Past blocks represent future regimes; finite-path tails and bootstrap stationarity can fail')]
    return [{'model_id': model, 'model_version': model, 'model_sha256': digest([code_sha, model]),
        'feature_version': FEATURE_VERSION, 'hypothesis': method[0], 'failure_conditions': method[1],
        'input_requirements': ['exact Binance daily-low rule', '720 causal minute returns', 'complete elapsed event window', 'fresh observed executable book'],
        'performance_criteria': ['event-disjoint verified-outcome Brier/log-loss versus contemporaneous market', 'calibration and uncertainty before any edge claim'],
        'risk_assumptions': 'Research only; [0,1] model uncertainty; no automatic admission, sizing or orders',
        'source_independence': 'Both challengers share Binance data and are NOT independent corroboration',
        'research_only': True, 'trading_authority': False, 'certification_authority': False}
        for model, method in zip(MODELS, methods)]


@lru_cache(maxsize=8)
def _resampled_minima(rows, start_ms, end_ms, seed):
    """512 reproducible paths with 15-minute blocks, including actual OHLC lows.

    Simulate all intervening minutes but test the barrier only inside the exact
    settlement window. Blocks use returns and low/previous-close jointly.
    """
    increments = tuple((math.log(b[3]/a[3]), math.log(b[2]/a[3])) for a, b in pairwise(rows))
    if len(increments) < 720:
        raise ValueError('minimum720_causal_returns_required')
    cursor = rows[-1][0]+60000
    minutes = math.ceil((end_ms-cursor)/60000)
    if not 1 <= minutes <= 4320:
        raise ValueError('bounded_challenger_horizon_required')
    rng = random.Random(seed)
    minima = []
    for _ in range(512):
        level, low, offset = 0., float('inf'), 0
        while offset < minutes:
            first = rng.randrange(len(increments)-15+1)
            for ret, intrabar in increments[first:first+15]:
                if cursor+offset*60000 >= start_ms:
                    low = min(low, level+intrabar)
                level += ret
                offset += 1
                if offset == minutes:
                    break
        minima.append(low)
    return tuple(minima)


def forecast_models(contract, evidence, *, cutoff):
    """Deterministic independent research estimates, with causal replay per call."""
    cutoff = at(cutoff)
    c = DomainContract.model_validate(contract.model_dump() if isinstance(contract, DomainContract) else contract)
    original = MarketSnapshot.model_validate(c.parameters.get('market_snapshot', {}))
    rebound = map_challenger_contract(original, now=cutoff)
    if (not c.compatible or c.review_required or max(c.timestamp, c.available_at) > cutoff
        or not rebound.compatible or rebound.review_required or rebound.parameters != c.parameters
        or (c.domain,c.contract_type,c.probability_semantics)!=(rebound.domain,rebound.contract_type,rebound.probability_semantics)
        or rebound.rules_sha256 != c.rules_sha256
        or (c.event_id, c.market_id, c.token_id) != (original.event_id, original.market_id, original.token_id)):
        raise ValueError('exact_causal_challenger_rule_binding_required')
    if len(evidence) != 1:
        raise ValueError('one_exact_replayed_external_source_required')
    e = DomainEvidence.model_validate(evidence[0]) if isinstance(evidence[0], dict) else evidence[0]
    candles = completed_minutes(e, cutoff=cutoff, symbol=c.parameters['symbol'])
    if len(candles) < 721:
        raise ValueError('minimum720_causal_returns_required')
    start, end = at(c.parameters['period_start_utc']), at(c.parameters['period_end_utc'])
    start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
    window = [r for r in candles if start_ms <= r['open_ms'] < end_ms]
    if start <= cutoff and (not window or window[0]['open_ms'] != start_ms or window[-1]['close_ms'] != e.payload['end_ms']):
        raise ValueError('complete_elapsed_event_window_required')
    threshold = c.parameters['threshold']
    if window and min(r['low'] for r in window) <= threshold:
        raise ValueError('barrier_already_observed_not_prospective_forecast')
    training = candles[-721:]
    returns = [math.log(b['close']/a['close']) for a,b in pairwise(training)]
    sigma, reference = stdev(returns), training[-1]['close']
    if not math.isfinite(sigma) or sigma <= 0 or not 60 <= (end-cutoff).total_seconds() <= 72*3600:
        raise ValueError('measured_variation_and_bounded_horizon_required')
    origin_ms = training[-1]['close_ms']+1
    remaining = (end_ms-max(start_ms, origin_ms))/60000
    gap = max(0., (start_ms-origin_ms)/60000)
    z = math.log(threshold/reference)
    def crossing(start_log):
        return 1. if start_log <= z else math.erfc((start_log-z)/(sigma*math.sqrt(2*remaining)))
    if gap:
        # Deterministic Gaussian quadrature in quantile coordinates; the
        # source is uncalibrated, so this numerical precision is NOT confidence.
        gaussian = sum(crossing(sigma*math.sqrt(gap)*NormalDist().inv_cdf((i+.5)/2048)) for i in range(2048))/2048
    else:
        gaussian = crossing(0.)
    rows = tuple((r['open_ms'], r['open'], r['low'], r['close']) for r in training)
    minima = _resampled_minima(rows, start_ms, end_ms, digest([e.content_sha256, start_ms, end_ms, MODELS[1]]))
    successes = sum(x <= z for x in minima)
    empirical = successes/len(minima)
    result = []
    for definition, yes in zip(enrollment_definitions(), (gaussian, empirical)):
        p = min(1., max(0., yes if c.parameters['selected_outcome']=='Yes' else 1-yes))
        result.append({**definition, 'status':'research_estimate', 'domain':'crypto',
            'event_id':c.event_id, 'market_id':c.market_id, 'token_id':c.token_id,
            'probability':p, 'lower_probability':0., 'upper_probability':1.,
            'probability_semantics':'binary_event_probability', 'calibration_status':'unvalidated_research',
            'independent_of_polymarket':True, 'dataset_sha256':digest([e.content_sha256]),
            'rules_sha256':c.rules_sha256, 'evidence_ids':[e.id], 'evidence_cutoff':cutoff.isoformat(),
            'source_lineages':[f"binance:{c.parameters['symbol']}"],
            'training_interval':[datetime.fromtimestamp(training[0]['open_ms']/1000,UTC).isoformat(), datetime.fromtimestamp(training[-1]['close_ms']/1000,UTC).isoformat()],
            'training_observations':len(training), 'training_returns':len(returns),
            'reference_price':reference, 'measured_sigma_per_sqrt_minute':sigma,
            'event_end_time':end.isoformat(), 'forecast_horizon_seconds':(end-cutoff).total_seconds(),
            'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_model_uncertainty_not_coverage_interval'},
            'monte_carlo':{'paths':512,'barrier_hits':successes,'block_minutes':15,'sampling_standard_error':math.sqrt(empirical*(1-empirical)/512),'scope':'simulation error only, not forecast uncertainty'} if definition['model_id']==MODELS[1] else None,
            'brier':None,'log_loss':None,'cost_adjusted_trading_edge':None})
    return result


SPORTS_MODELS = ('nfl-davidson-team-strength-v23.1','nfl-ternary-frequency-v23.1')


def forecast_nfl(market, data, *, cutoff):
    """Unconditional ternary Davidson team strength vs existing ternary frequency.

    Davidson likelihood models ties explicitly; ordinary Elo expected score is
    never substituted for a win probability. Source adapter must have verified
    raw publisher bytes before this pure replay. NFL result data is community
    nflverse evidence, not independent official settlement verification.
    """
    from collections import Counter

    from neraium_poly.research.phase13.mapping import map_market
    from neraium_poly.research.phase13.models import predict_game, training_games
    from neraium_poly.research.phase13.runtime import SportsResearchRuntime

    cutoff=at(cutoff);m=MarketSnapshot.model_validate(market)
    if any(a.available_at>cutoff for a in data['artifacts']):
        raise ValueError('sports_source_available_after_forecast')
    mapping=map_market(m,data['games'],now=cutoff);target=SportsResearchRuntime._target(data,mapping)
    baseline=predict_game(data['games'],target,mapping.selected_team_id,cutoff,method='frequency')
    games=training_games(data['games'],target,cutoff)
    counts=Counter(team for g in games for team in (g.home_id,g.away_id))
    if len(games)<50 or min(counts[target.home_id],counts[target.away_id])<10:
        raise ValueError('insufficient_causal_nfl_training')
    ratings={};ties=0;past=0
    def probabilities(home,away,tie_rate):
        # Davidson tie mass nu*sqrt(ability_home*ability_away).
        a=math.exp(max(-12.,min(12.,home+.2)));b=math.exp(max(-12.,min(12.,away)))
        nu=2*tie_rate/(1-tie_rate);t=nu*math.sqrt(a*b);den=a+b+t
        return a/den,t/den,b/den
    for g in games:
        h,a=ratings.get(g.home_id,0.),ratings.get(g.away_id,0.)
        win,tie,loss=probabilities(h,a,(ties+.5)/(past+1))
        actual=1. if g.home_score>g.away_score else 0. if g.home_score<g.away_score else .5
        delta=.1*(actual-win-.5*tie)
        ratings[g.home_id]=h+delta;ratings[g.away_id]=a-delta
        ties+=g.home_score==g.away_score;past+=1
    win,tie,loss=probabilities(ratings.get(target.home_id,0.),ratings.get(target.away_id,0.),(ties+.5)/(past+1))
    if mapping.selected_team_id==target.away_id:win,loss=loss,win
    distributions=({'win':win,'tie':tie,'loss':loss},baseline.uncertainty['outcome_probabilities'])
    code=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return [{'model_id':name,'model_version':name,'model_sha256':digest([code,name]),
        'feature_version':'causal-independent-NFL-results-davidson-or-frequency-v1',
        'status':'research_estimate','domain':'sports','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
        'probability_semantics':'outcome_distribution','probability':probs['win'],'outcome_probabilities':probs,
        'expected_payout':probs['win']+.5*probs['tie'],'expected_payout_is_not_win_probability':True,
        'lower_probability':0.,'upper_probability':1.,'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_model_uncertainty_not_coverage_interval'},
        'dataset_sha256':digest([g.model_dump(mode='json') for g in games]),'rules_sha256':mapping.rules_sha256,
        'sports_mapping':mapping.model_dump(mode='json'),'training_observations':len(games),
        'training_interval':[games[0].starts_at.isoformat(),games[-1].starts_at.isoformat()],
        'training_game_ids':[g.game_id for g in games],'latest_result_available_at':max(g.result_observed_at for g in games).isoformat(),
        'evidence_cutoff':cutoff.isoformat(),'event_end_time':target.starts_at.isoformat(),
        'forecast_horizon_seconds':(target.starts_at-cutoff).total_seconds(),
        'source_lineages':['nflverse:games.csv'],'independent_of_polymarket':True,
        'calibration_status':'unvalidated_research','brier':None,'log_loss':None,
        'limitations':['Tie model and constant team strengths are uncalibrated','No injuries, lineups or roster adjustment','Community results require official corroboration for settlement','No historical availability claim before actual snapshot retrieval'],
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for name,probs in zip(SPORTS_MODELS,distributions)]


def enrollment_definitions():
    code=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return _crypto_enrollment_definitions()+[{'model_id':name,'model_version':name,
        'model_sha256':digest([code,name]),'feature_version':'causal-independent-NFL-results-davidson-or-frequency-v1',
        'hypothesis':hypothesis,'input_requirements':['verified nflverse raw snapshot','exact NFL moneyline mapping with half-payoff ties','50 causal league results and10perparticipant'],
        'performance_criteria':['ternary verified-outcome scoring','expected-payout baseline comparison separated from win probability'],
        'risk_assumptions':'Uncalibrated research only, uncertainty[0,1], no orders',
        'failure_conditions':['roster drift','unmodeled lineup and injuries','tie-rate instability'],
        'source_independence':'Both NFL models share nflverse and are not independent corroboration',
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for name,hypothesis in zip(SPORTS_MODELS, ['Online Davidson team-strength with explicit tie likelihood','Existing causal ternary participant frequency baseline'])]
