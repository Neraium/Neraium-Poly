"""Research-only tie-aware settlement-payout forecasting; no execution authority."""
import csv
import hashlib
import io
import math
import random
import re
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import finance

MODEL = 'spx-weekday-dirichlet-payout-v27.1'
BASELINE_MODEL = 'spx-global-dirichlet-payout-v27.1'
OUTCOMES = ('up', 'tie', 'down')
PAYOUTS = {'up': 1., 'tie': .5, 'down': 0.}
AUTHORITY = {'research_only': True, 'trading_authority': False, 'certification_authority': False}
NY = ZoneInfo('America/New_York')


def definitions():
    weekday = {'model_id': MODEL, 'model_version': MODEL,
             'model_sha256': digest([MODEL, hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]),
             'domain': 'finance', 'feature_version': 'completed-SPX-cent-direction-weekday-v1',
             'hypothesis': 'Weekday-conditioned categorical closing direction retaining ties improves expected payout versus global historical frequency',
             'target': 'ordinary completed reference-compatible session; Up pays1/.5/0 on rise/tie/fall',
             'features': ['prior rounded completed closes', 'target weekday'],
             'hyperparameters': {'window': 252, 'dirichlet_alpha': .5, 'minimum_weekday_events': 12},
             'calibration_status': 'unvalidated_research', 'operational_authorization': 'research_only',
             'failure_conditions': ['reference mismatch', 'halt/fallback', 'publication-time uncertainty', 'weekday instability', 'small sample'],
             **AUTHORITY}
    global_model = {**weekday, 'model_id': BASELINE_MODEL, 'model_version': BASELINE_MODEL,
                    'model_sha256': digest([BASELINE_MODEL, hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]),
                    'hypothesis': 'All-weekday tie-aware Dirichlet frequency is a simple independent expected-payout baseline, not asserted superior',
                    'features': ['prior rounded completed closes'],
                    'hyperparameters': {'window': 252, 'dirichlet_alpha': .5, 'minimum_training_events': 30}}
    return [weekday, global_model]


def _at(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('aware_source_timestamp_required')
    return result.astimezone(UTC)


def _rows(rows):
    if not isinstance(rows, (list, tuple)) or not 30 <= len(rows) <= 4000:
        raise ValueError('30_to4000_authentic_observations_required')
    result = []; seen = set()
    for row in rows:
        event = row['event_id']; event_time = _at(row['event_time']); available = _at(row['available_at'])
        if (not isinstance(event, str) or not event or event in seen or row['outcome'] not in OUTCOMES
            or event != 'SPX:'+event_time.astimezone(NY).date().isoformat()
            or event_time > available or not re.fullmatch('[0-9a-f]{64}', row['source_sha256'])):
            raise ValueError('unique_known_outcome_with_source_provenance_required')
        seen.add(event)
        result.append({'event_id': event, 'event_time': event_time.isoformat(), 'available_at': available.isoformat(),
                       'outcome': row['outcome'], 'source_sha256': row['source_sha256']})
    if result != sorted(result, key=lambda x: (x['event_time'], x['event_id'])):
        raise ValueError('chronologically_ordered_events_required')
    return result


def _distribution(rows):
    counts = Counter(r['outcome'] for r in rows); total = len(rows)+1.5
    return {k: (counts[k]+.5)/total for k in OUTCOMES}


def _payout(distribution):
    return sum(distribution[k]*PAYOUTS[k] for k in OUTCOMES)


def fit_payout_posterior(rows, *, cutoff, weekday=None):
    """Use only already-observed outcomes; interval covers parameters, not model error."""
    records = _rows(rows); cutoff = _at(cutoff)
    if any(max(_at(r['event_time']), _at(r['available_at'])) > cutoff for r in records):
        raise ValueError('future_or_unavailable_training_outcome')
    if weekday is not None and (type(weekday) is not int or not 0 <= weekday <= 4):
        raise ValueError('target_weekday_required')
    records = records[-252:]
    selected = [r for r in records if weekday is None or _at(r['event_time']).astimezone(NY).weekday() == weekday]
    if len(selected) < (12 if weekday is not None else 30):
        raise ValueError('insufficient_chronological_target_weekday_events')
    counts = Counter(r['outcome'] for r in selected); distribution = _distribution(selected)
    model_id = MODEL if weekday is not None else BASELINE_MODEL
    rng = random.Random(digest([model_id, selected, weekday])); draws = []
    for _ in range(1024):
        values = {k: rng.gammavariate(counts[k]+.5, 1.) for k in OUTCOMES}; total = sum(values.values())
        draws.append(sum(values[k]*PAYOUTS[k] for k in OUTCOMES)/total)
    draws.sort()
    return {'model_id': model_id, 'dataset_sha256': digest(selected), 'observations': len(selected),
            'event_ids': [r['event_id'] for r in selected], 'training_interval': [selected[0]['event_time'], selected[-1]['event_time']],
            'availability_cutoff': cutoff.isoformat(), 'outcome_probabilities': distribution,
            'expected_up_payout': _payout(distribution), 'parameter_credible_interval_95': [draws[25], draws[998]],
            'interval_scope': 'Dirichlet parameter uncertainty only; not calibrated event or model-error bounds',
            'calibration_status': 'unvalidated_research', **AUTHORITY}


def spx_observations(evidence, *, cutoff):
    """Parse authentic current observed FRED snapshot, never infer old availability."""
    e, payload = finance.evidence_payload(evidence, url=finance.URL, domain='finance',
        provider='Federal Reserve Bank of St. Louis FRED', series='SP500', cutoff=_at(cutoff))
    values = []; seen = set()
    for row in csv.DictReader(io.StringIO(payload['raw_response_utf8'])):
        close = datetime.strptime(row['observation_date'], '%Y-%m-%d').replace(hour=16, tzinfo=NY).astimezone(UTC)
        if close in seen or close > _at(cutoff):
            raise ValueError('unique_pre_cutoff_SPX_dates_required')
        seen.add(close)
        if row['SP500'] in {'', '.', 'NA'}:
            continue
        value = Decimal(row['SP500']).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if not value.is_finite() or value <= 0:
            raise ValueError('positive_finite_SPX_close_required')
        values.append((close, value))
    if values != sorted(values) or not 253 <= len(values) <= 4000 or (_at(cutoff)-values[-1][0]).total_seconds() > 7*86400:
        raise ValueError('current_ordered_SPX_source_history_required')
    result = []
    for previous, current in pairwise(values):
        t, value = current; outcome = 'up' if value > previous[1] else 'down' if value < previous[1] else 'tie'
        result.append({'event_id': 'SPX:'+t.astimezone(NY).date().isoformat(), 'event_time': t.isoformat(),
                       'available_at': e.available_at.isoformat(), 'outcome': outcome, 'source_sha256': payload['raw_response_sha256']})
    return result


def derive_spx_payout(study, original_forecast, *, market, book, cutoff, model_id=BASELINE_MODEL):
    """Make a new, current prospective research estimate from replayable prior evidence."""
    cutoff = _at(cutoff); f = original_forecast
    members = [x for x in study.get('forecasts', []) if x.get('id') == f.get('id')]
    if len(members) != 1 or digest(members[0]) != digest(f):
        raise ValueError('exact_original_forecast_membership_required')
    if max(_at(study['timestamp']), _at(study['available_at'])) > cutoff:
        raise ValueError('original_study_not_available_before_challenger')
    definition = next((d for d in definitions() if d['model_id'] == model_id), None)
    if definition is None:
        raise ValueError('known_frozen_payout_model_required')
    if f.get('adapter') != 'finance' or f.get('model_id') not in finance.MODELS:
        raise ValueError('supported_original_SPX_model_required')
    byid = {e['id']: e for e in study['evidence']}
    if len(byid) != len(study['evidence']):
        raise ValueError('unique_original_external_evidence_required')
    evidence = [byid[x] for x in f['evidence_ids']]
    finance.replay(f, evidence, as_of=cutoff)
    m = MarketSnapshot.model_validate(market.model_dump() if hasattr(market, 'model_dump') else market)
    mapping = finance.supports(m, cutoff=cutoff)
    if (not mapping['supported'] or any(getattr(m, k) != f[k] for k in ('market_id', 'token_id', 'event_id'))
        or mapping['contract']['rules_sha256'] != f['rules_sha256'] or m.outcome != f['market']['outcome']):
        raise ValueError('same_unstarted_exact_SPX_contract_required')
    contract = mapping['contract']
    # Rechecks source age, actual availability, correct cash-index identity and exact rules at NEW cutoff.
    finance.estimates(contract, evidence, cutoff=cutoff)
    records = spx_observations(evidence, cutoff=cutoff)
    posterior = fit_payout_posterior(records, cutoff=cutoff, weekday=contract['target_weekday'] if model_id == MODEL else None)
    d = posterior['outcome_probabilities']; payout = posterior['expected_up_payout']
    if m.outcome == 'Down':
        payout = 1-payout
    conditioning = 'ordinary completed FRED/WSJ-compatible session including ties; halt/fallback/calendar risk unmodeled'
    forecast_contract = {**contract, 'conditioning': conditioning, 'original_contract_conditioning': contract['conditioning'],
                         'probability_semantics': 'expected_payout',
                         'settlement_payouts': PAYOUTS if m.outcome == 'Up' else {k: 1-v for k, v in PAYOUTS.items()}}
    result = {'model_id': model_id, 'model_version': model_id, 'model_sha256': definition['model_sha256'],
              'feature_version': definition['feature_version'], 'domain': 'finance', 'event_id': m.event_id,
              'market_id': m.market_id, 'token_id': m.token_id, 'probability': payout, 'expected_payout': payout,
              'probability_semantics': 'expected_payout', 'outcome_probabilities': d,
              'lower_probability': 0., 'upper_probability': 1., 'uncertainty': 1.,
              'parameter_credible_interval_95': posterior['parameter_credible_interval_95'] if m.outcome == 'Up' else [1-posterior['parameter_credible_interval_95'][1], 1-posterior['parameter_credible_interval_95'][0]],
              'interval_scope': posterior['interval_scope'], 'dataset_sha256': posterior['dataset_sha256'],
              'training_observations': posterior['observations'], 'training_event_ids': posterior['event_ids'],
              'training_interval': posterior['training_interval'], 'evidence_ids': f['evidence_ids'],
              'evidence_cutoff': cutoff.isoformat(), 'event_end_time': contract['period_end'],
              'rules_sha256': f['rules_sha256'], 'contract': forecast_contract, 'source_lineages': f['source_lineages'],
              'original_forecast_id': f['id'], 'original_forecast_sha256': digest(f),
              'original_study_id': study['id'], 'original_study_sha256': digest(study),
              'original_target_conditioning': f.get('target_conditioning'),
              'target_conditioning': conditioning,
              'unconditional_contract_probability': False, 'calibration_status': 'unvalidated_research',
              'limitations': ['Expected token payout is not a binary event probability', 'Historical publication vintages/WSJ matching unverified',
                             'No prospective calibration or independently demonstrated executable advantage', 'No cancellation/halt/fallback probability model'],
              **AUTHORITY}
    b = OrderBookSnapshot.model_validate(book.model_dump() if hasattr(book, 'model_dump') else book)
    bound = finance.bind_predictions([result], m, b, cutoff)[0]
    bound.pop('native_book_provenance', None)  # Raw current quote evidence belongs to the collector/frame journal.
    bound['id'] = digest([model_id, bound])
    return bound


def replay_spx_payout(forecast, study, original_forecast, *, as_of):
    if not _at(forecast['timestamp']) <= _at(as_of):
        raise ValueError('future_challenger_forecast_replay')
    expected = derive_spx_payout(study, original_forecast, market=forecast['market'],
                                book=forecast['book'], cutoff=forecast['timestamp'], model_id=forecast['model_id'])
    if any(digest(forecast.get(k)) != digest(v) for k, v in expected.items()):
        raise ValueError('payout_challenger_source_model_replay_mismatch')
    return {'verified': True, 'forecast_id': forecast['id'], 'dataset_sha256': forecast['dataset_sha256'], **AUTHORITY}


def _metrics(distributions, rows):
    ps = [_payout(d) for d in distributions]; ys = [PAYOUTS[r['outcome']] for r in rows]
    return {'squared_payout_error': mean((p-y)**2 for p, y in zip(ps, ys)),
            'categorical_log_loss': mean(-math.log(d[r['outcome']]) for d, r in zip(distributions, rows)),
            'multiclass_brier_score': mean(sum((d[k]-int(k == r['outcome']))**2 for k in OUTCOMES) for d, r in zip(distributions, rows)),
            'binary_brier_score': None, 'binary_log_loss': None,
            'binary_metric_reason': 'Fractional settlement payout target is not a Bernoulli label',
            'reliability': [{'bin': [i/5, (i+1)/5], 'count': len(items),
                             'mean_forecast_payout': mean(x[0] for x in items), 'mean_realized_payout': mean(x[1] for x in items)}
                            for i in range(5) if (items := [(p, y) for p, y in zip(ps, ys) if i/5 <= p <= (i+1)/5 and (i == 4 or p < (i+1)/5)])]}


def evaluate_payout_challenger(rows, *, reconstructed=False):
    """Frozen50/25/25 event split; calibrator never sees heldout outcomes."""
    if type(reconstructed) is not bool:
        raise ValueError('explicit_reconstruction_scope_required')
    records = _rows(rows)[-252:]
    if len(records) < 120:
        raise ValueError('120_event_chronological_comparison_required')
    n = len(records); train = records[:n//2]; calibration = records[n//2:3*n//4]; heldout = records[3*n//4:]
    first_cal = datetime.combine(_at(calibration[0]['event_time']).astimezone(NY).date(), time(9, 30), NY).astimezone(UTC)
    first_test = datetime.combine(_at(heldout[0]['event_time']).astimezone(NY).date(), time(9, 30), NY).astimezone(UTC)
    if not reconstructed and (any(_at(r['available_at']) > first_cal for r in train)
        or any(_at(r['available_at']) > first_test for r in calibration)):
        raise ValueError('historical_predecision_availability_unverified')
    fit_cutoff = max(_at(r['available_at']) for r in train)+timedelta(microseconds=1) if reconstructed else first_cal
    baseline = _distribution(train)
    byday = {d: fit_payout_posterior(train, cutoff=fit_cutoff, weekday=d)['outcome_probabilities'] for d in range(5)}
    def predictions(part, weight):
        return [{k: weight*byday[_at(r['event_time']).astimezone(NY).weekday()][k]+(1-weight)*baseline[k] for k in OUTCOMES} for r in part]
    weights = (0., .25, .5, .75, 1.)
    weight = min(weights, key=lambda w: (_metrics(predictions(calibration, w), calibration)['squared_payout_error'], w))
    base = [baseline]*len(heldout); raw = predictions(heldout, 1.); calibrated = predictions(heldout, weight)
    y = [PAYOUTS[r['outcome']] for r in heldout]
    improvements = [(p-y0)**2-(_payout(d)-y0)**2 for p, d, y0 in zip([_payout(baseline)]*len(y), calibrated, y)]
    rng = random.Random(2701); draws = []; block = 5
    for _ in range(1000):
        sample = []
        while len(sample) < len(improvements):
            start = rng.randrange(len(improvements)); sample.extend(improvements[(start+j)%len(improvements)] for j in range(block))
        draws.append(mean(sample[:len(improvements)]))
    draws.sort(); interval = [draws[24], draws[974]]
    return {'protocol': 'phase27-payout-v1', 'model': definitions()[0],
            'dataset_sha256': digest(records), 'split': {'training': len(train), 'calibration': len(calibration), 'heldout': len(heldout)},
            'event_ids': {name: [r['event_id'] for r in part] for name, part in [('training', train), ('calibration', calibration), ('heldout', heldout)]},
            'training_interval': [train[0]['event_time'], train[-1]['event_time']],
            'calibration_interval': [calibration[0]['event_time'], calibration[-1]['event_time']],
            'heldout_interval': [heldout[0]['event_time'], heldout[-1]['event_time']],
            'calibration_weight': weight, 'calibration_weight_selection': 'calibration squared payout error only; tie chooses simpler baseline',
            'global_frequency_baseline': _metrics(base, heldout),
            'neutral_payout_baseline': {'squared_payout_error': mean((.5-y0)**2 for y0 in y),
                                        'target': 'constant0.5payout no-skill comparison, not a learned forecast'},
            'weekday_raw': _metrics(raw, heldout),
            'weekday_calibrated': _metrics(calibrated, heldout),
            'heldout_squared_payout_error_improvement': mean(improvements), 'block_bootstrap_interval_95': interval,
            'bootstrap': {'resamples': 1000, 'block_events': 5, 'seed': 2701, 'assumption': 'local block dependence approximation, not proof of independent returns'},
            'statistically_supported_advantage': False,
            'reason': 'Exploratory historical reconstruction cannot establish prospective advantage' if reconstructed else 'Single small heldout cohort; further independent prospective replication required',
            'historical_reconstruction': reconstructed, 'point_in_time_historical_availability_verified': not reconstructed,
            'effective_sample_size': None, 'statistically_independent_event_count': 0,
            'qualified_certification_training_events': 0, 'qualified_certification_heldout_events': 0,
            'market_baseline': None, 'market_baseline_reason': 'Contemporaneous market probability and executable historical depth unavailable',
            'net_trading_performance': None, 'limitations': ['Common-asset serial dependence; unique event IDs are not statistical independence',
                'No untouched external dataset after prior phase exposure', 'Current-vintage observations are not verified original settlement records',
                'Squared payout accuracy is distinct from profitable executable edge'], **AUTHORITY}
