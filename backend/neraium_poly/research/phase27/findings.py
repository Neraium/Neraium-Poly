"""Current executable-price findings beside immutable research forecasts.

The caller must independently replay original models before passing verified IDs.
fee_quotes maps forecast IDs to {"evidence": exact decision-cost/calibration proof,
"verifier": callable}. A recorded verified flag is never a verifier. This module
neither supplies probabilities nor grants order, risk or certification authority.
"""
import hashlib
import json
import math
from collections import defaultdict

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.capacity import capacity_scenarios
from neraium_poly.research.phase25.competition import cohort_key, executable_diagnostic
from neraium_poly.research.phase25.dependencies import AUTHORITY, at, bound_forecasts, canonical_event

VERSION = 'phase27-current-findings-v1'
FORECAST_MAX_AGE_SECONDS = 300
MAX_FINDINGS = 512
MAX_LEVELS = 1000


def _number(value, low=0., high=1.):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _current(frame, now):
    raw = frame.model_dump(mode='json') if hasattr(frame, 'model_dump') else frame
    if not isinstance(raw, dict) or raw.get('mode') != 'real_market_data':
        raise ValueError('genuine_public_market_frame_required')
    if not (at(raw['timestamp']) <= at(raw['available_at']) <= now
            and 0 <= (now-at(raw['timestamp'])).total_seconds() <= 15):
        raise ValueError('fresh_causal_market_frame_required')
    health = raw.get('producer_health', {})
    if isinstance(health, dict) and health.get('status') not in (None, 'ok', 'healthy'):
        raise ValueError('current_producer_health_not_qualified')
    markets, books, bad = {}, {}, set()
    for field, dest, schema in [('markets', markets, MarketSnapshot), ('books', books, OrderBookSnapshot)]:
        rows = raw.get(field, ())
        if not isinstance(rows, (list, tuple)) or len(rows) > 4096:
            raise ValueError('bounded_current_market_frame_required')
        for value in rows:
            value = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
            try:
                token = value['token_id']
                if not isinstance(token, str) or not token or len(token) > 512:
                    raise ValueError('bounded_native_token_identity_required')
                if field == 'books' and (len(value.get('asks', ())) > MAX_LEVELS or len(value.get('bids', ())) > MAX_LEVELS):
                    bad.add(token); continue
                parsed = schema.model_validate(value)
                if token in dest and digest(dest[token].model_dump(mode='json')) != digest(parsed.model_dump(mode='json')):
                    bad.add(token)
                else:
                    dest[token] = parsed
            except (ValueError, KeyError, TypeError):
                token = value.get('token_id') if isinstance(value, dict) else None
                if isinstance(token, str):bad.add(token)
    return raw, markets, books, bad


def _expected_payout(f):
    if f.get('probability_semantics') != 'expected_payout':return None
    probabilities = f.get('outcome_probabilities', {})
    if not isinstance(probabilities, dict):return None
    if (set(probabilities) != {'up', 'tie', 'down'}
            or not all(_number(x) for x in probabilities.values())
            or abs(sum(probabilities.values())-1) > 1e-9
            or 'original_target_conditioning' not in f
            or not isinstance(f.get('original_forecast_id'), str)
            or not isinstance(f.get('original_forecast_sha256'), str)
            or len(f['original_forecast_sha256']) != 64):return None
    side = str(f.get('contract', {}).get('selected_outcome', '')).lower()
    if side not in ('up', 'down'):return None
    payouts = f.get('contract', {}).get('settlement_payouts')
    required = {'up': 1., 'tie': .5, 'down': 0.} if side == 'up' else {'up': 0., 'tie': .5, 'down': 1.}
    if not isinstance(payouts, dict) or payouts != required:return None
    value = sum(probabilities[k]*payouts[k] for k in ('up', 'tie', 'down'))
    if not _number(f.get('expected_payout')) or abs(value-f['expected_payout']) > 1e-9:return None
    if not _number(f.get('probability')) or abs(value-f['probability']) > 1e-9:return None
    return value


def _cost_context(f, study, decision, fee_quotes, now):
    bundle = fee_quotes.get(f['id']) if isinstance(fee_quotes, dict) else None
    if not isinstance(bundle, dict) or not isinstance(bundle.get('evidence'), dict) or not callable(bundle.get('verifier')):
        return None, None, 'independent_exact_calibration_and_cost_replay_required'
    costs = bundle['evidence']
    try:exact_decision = at(costs['decision_at']) == now
    except (KeyError, ValueError, TypeError):exact_decision = False
    if (costs.get('original_forecast_sha256') != digest(f)
            or costs.get('original_study_sha256') != digest(study)
            or not exact_decision):
        return None, None, 'exact_original_and_decision_cost_binding_required'
    return costs, bundle['verifier'], None


def _probe(book, forecast, costs, *, budget=5.):
    """Conservative research sweep, never an order or a realized fill.

    Charge all costs against the finite five-dollar probe budget; consume at most
    10% of each displayed level and stop when marginal net edge falls below .03.
    Entry survival, queue priority and future exit depth remain unverified.
    """
    lower, fee = forecast['lower_probability'], costs['fee_rate']
    other = sum(costs[k] for k in ('slippage_per_share', 'latency_adverse_selection_per_share',
                                  'capital_lockup_cost_per_share', 'settlement_risk_cost_per_share'))
    spent = principal = quantity = net = 0.
    marginal_stop = False
    for level in book.asks:
        cost = level.price*(1+fee)+other
        edge = lower*(1-fee)-cost
        if edge < .03:
            marginal_stop = True; break
        take = min(level.size*.1, max(0., budget-spent)/cost)
        quantity += take; principal += take*level.price; spent += take*cost; net += take*edge
        if spent >= budget-1e-9:break
    enough = quantity+1e-9 >= forecast['market']['min_order_size'] and principal >= 2-1e-9
    return {'probe_budget_usd': budget, 'participation_fraction': .1,
            'supported_shares': quantity, 'entry_principal_usd': principal,
            'modeled_total_cost_usd': spent, 'entry_vwap': principal/quantity if quantity else None,
            'conservative_expected_net_value_usd': net if enough else None,
            'minimum_lot_and_notional_supported': enough, 'edge_limited': marginal_stop,
            'partial_budget_support': spent < budget-1e-9, 'hypothetical_only': True,
            'actual_fill': False, 'future_exit_liquidity_verified': False, **AUTHORITY}


def _relationship_context(raw, market_id, now):
    result = []
    relations = raw.get('relationships', ())
    evidence = raw.get('evidence', ())
    if not isinstance(relations, (tuple, list)) or not isinstance(evidence, (tuple, list)):
        return result
    byid = {e.get('relationship_id'): e for e in evidence[:2048] if isinstance(e, dict)}
    for rel in relations[:2048]:
        if not isinstance(rel, dict) or market_id not in rel.get('market_ids', ()):continue
        try:
            if at(rel['timestamp']) > at(rel['available_at']) or at(rel['available_at']) > now:continue
            ev = byid.get(rel.get('id'), {})
            if ev and (at(ev['timestamp']) > at(ev['available_at']) or at(ev['available_at']) > now):continue
            result.append({'relationship_id': rel.get('id'), 'kind': rel.get('kind'),
                           'source': rel.get('source'), 'source_timestamp': rel['timestamp'],
                           'available_at': rel['available_at'], 'persistence': ev.get('persistence'),
                           'recorded_qualified_flag': ev.get('qualified'),
                           'independently_replayed': False, 'causal_effect_verified': False,
                           'scope': 'observed context only; stored flags never establish logical constraints, forecasting benefit or executable edge'})
        except (KeyError, ValueError, TypeError):continue
        if len(result) == 8:break
    return result


def build_findings(studies, frame, *, as_of, verified_forecast_ids=(), fee_quotes=None):
    """Bound fresh observations to original hypotheses; rank qualified modeled EV.

    Forecasts older than300s are retained as rejections, never redated. Every
    current book remains linked to its full parent frame by content hash. Ranking
    uses a <=$5 depth-aware research probe, not probability gap or large-bankroll
    extrapolation. Portfolio/risk/strategy admission are always separate.
    """
    now = at(as_of)
    raw, markets, books, bad = _current(frame, now)
    found, rejected = bound_forecasts(studies, as_of=now)
    if not isinstance(verified_forecast_ids, (list, tuple, set, frozenset)) or len(verified_forecast_ids) > 10000:
        raise ValueError('bounded_replayed_forecast_id_collection_required')
    verified = set(verified_forecast_ids)
    findings, cohorts = [], defaultdict(list)
    frame_sha = digest(raw)
    candidates = sorted(found.values(), key=lambda x: (at(x['forecast']['timestamp']), x['forecast']['id']), reverse=True)
    deferred = max(0, len(candidates)-MAX_FINDINGS)
    for bound in candidates[:MAX_FINDINGS]:
        f, study = bound['forecast'], bound['study']
        try:original_sha, study_sha = digest(f), digest(study)
        except (ValueError, TypeError):
            rejected['noncanonical_original_record_payload'] += 1
            continue
        reasons, group, tags = [], None, []
        m, b = markets.get(f['token_id']), books.get(f['token_id'])
        row = {'id': digest([VERSION, f['id'], original_sha, frame_sha, now.isoformat()]),
               'forecast_id': f['id'], 'model_id': f.get('model_id', f.get('model_version')),
               'model_version': f.get('model_version'), 'model_sha256': f.get('model_sha256'),
               'feature_version': f.get('feature_version'), 'domain': f.get('domain'),
               'market_id': f['market_id'], 'event_id': f['event_id'], 'token_id': f['token_id'],
               'original_study_id': study['id'], 'original_study_sha256': study_sha,
               'original_forecast_sha256': original_sha, 'forecast_timestamp': f['timestamp'],
               'evidence_cutoff': f['evidence_cutoff'], 'evidence_ids': f.get('evidence_ids', []),
               'evidence_lineages': f.get('source_lineages', []), 'resolution_rules_sha256': f['rules_sha256'],
               'resolution_source': f['market'].get('resolution_source'),
               'forecast_probability': f.get('probability') if f.get('probability_semantics') != 'expected_payout' else None,
               'expected_payout': _expected_payout(f), 'probability_semantics': f.get('probability_semantics'),
               'original_target_conditioning': f.get('original_target_conditioning'),
               'original_contract_conditioning': f.get('original_contract_conditioning'),
               'target_conditioning': f.get('target_conditioning', f.get('conditioning')),
               'uncertainty': {'lower': f.get('lower_probability'), 'upper': f.get('upper_probability'),
                               'calibration_status': f.get('calibration_status'), 'confidence_level': None},
               'decision_at': now.isoformat(), 'frame_id': raw['id'], 'frame_sha256': frame_sha,
               'book_id': b.id if b else None, 'book_sha256': digest(b.model_dump(mode='json')) if b else None,
               'book_source_timestamp': b.timestamp.isoformat() if b else None,
               'book_available_at': b.available_at.isoformat() if b else None,
               'book_source': b.source if b else None,
               'full_book_reference': 'original full decision frame identified by frame_id/frame_sha256',
               'observed_best_ask': b.asks[0].price if b and b.asks else None,
               'observed_best_bid': b.bids[0].price if b and b.bids else None,
               'executable_ask': None, 'executable_bid': None,
               'market_midpoint': (b.asks[0].price+b.bids[0].price)/2 if b and b.asks and b.bids else None,
               'spread': b.asks[0].price-b.bids[0].price if b and b.asks and b.bids else None,
               'gross_probability_gap_to_ask': None, 'gross_modeled_payout_gap_to_ask': None,
               'estimated_after_cost_edge': None,
               'standard_probe': None, 'capacity': None, 'fee_and_cost_evidence_sha256': None,
               'confidence_status': 'unvalidated_research', 'finding_rank': None,
               'correlation': {'canonical_group_id': None, 'dependency_tags': [], 'independence_verified': False},
               'settlement_risk': {'rules_match_current_market': False, 'resolution_finality_verified': False,
                                   'expected_capital_lockup_seconds': None,
                                   'status': 'future_settlement_and_redemption_timing_unverified'},
               'relationship_context': _relationship_context(raw, f['market_id'], now),
               'status': 'withheld', 'reasons': reasons, 'execution_authorized': False, **AUTHORITY}
        if f['id'] not in verified:reasons.append('independent_original_source_model_replay_required')
        age = (now-at(f['timestamp'])).total_seconds()
        row['forecast_age_seconds'] = age
        if not 0 <= age <= FORECAST_MAX_AGE_SECONDS:reasons.append('forecast_outside_frozen_300_second_decision_window')
        if f['token_id'] in bad:reasons.append('ambiguous_or_oversize_current_token_observation')
        if m is None:reasons.append('current_exact_market_metadata_missing')
        elif (m.market_id != f['market_id'] or m.event_id != f['event_id'] or m.token_id != f['token_id']
              or m.exchange != 'polymarket' or m.status != 'active' or m.available_at > now
              or hashlib.sha256(m.resolution_rules.encode()).hexdigest() != f['rules_sha256']
              or not m.resolution_rules.strip()
              or m.resolution_source != f['market'].get('resolution_source')
              or f['market'].get('outcome') is not None and m.outcome != f['market']['outcome']
              or f['market'].get('question') is not None and m.question != f['market']['question']
              or f['market'].get('end_time') is not None and m.end_time != at(f['market']['end_time'])):
            reasons.append('current_market_or_resolution_identity_changed')
        else:row['settlement_risk']['rules_match_current_market'] = True
        if m and m.end_time is not None and m.end_time <= now:reasons.append('native_market_trading_horizon_ended')
        if not now < at(f['event_end_time']):reasons.append('forecast_event_decision_horizon_ended')
        if b is None:reasons.append('current_executable_book_missing')
        elif b.source not in PUBLIC_BOOK_SOURCES or b.exchange != 'polymarket' or b.market_id != f['market_id'] or b.token_id != f['token_id']:
            reasons.append('public_executable_book_identity_required')
        else:
            reasons += list(assess_book(b, now, max_spread=.05, expected_token=f['token_id']).reasons)
            if not 0 <= (now-b.available_at).total_seconds() <= 15:reasons.append('current_book_receipt_outside_15_seconds')
            if len({x.price for x in b.asks}) != len(b.asks) or len({x.price for x in b.bids}) != len(b.bids):reasons.append('unique_native_depth_levels_required')
        quote_healthy = bool(b and f['token_id'] not in bad and row['settlement_risk']['rules_match_current_market']
            and b.source in PUBLIC_BOOK_SOURCES and b.exchange == 'polymarket' and b.market_id == f['market_id']
            and b.token_id == f['token_id'] and assess_book(b, now, max_spread=.05).healthy
            and 0 <= (now-b.available_at).total_seconds() <= 15
            and (m.end_time is None or m.end_time > now)
            and len({x.price for x in b.asks}) == len(b.asks) and len({x.price for x in b.bids}) == len(b.bids))
        row['book_qualified_for_current_observation'] = quote_healthy
        if quote_healthy:
            row['executable_ask'], row['executable_bid'] = b.asks[0].price, b.bids[0].price
        if not reasons:
            row['executable_ask'] = b.asks[0].price
            row['executable_bid'] = b.bids[0].price
            payout = _expected_payout(f)
            if payout is not None:
                row['gross_modeled_payout_gap_to_ask'] = payout-b.asks[0].price
                row['confidence_status'] = 'conditional_expected_payout_unvalidated_research'
        if f.get('probability_semantics') == 'expected_payout':
            reasons.append('expected_payout_requires_separate_calibrated_token_valuation_protocol')
            reasons.append('native_reference_and_fallback_compatibility_not_independently_validated')
        if (f.get('target_conditioning') or f.get('conditioning') or f.get('unconditional_contract_probability') is False
                or f.get('probability_semantics') != 'binary_event_probability' or f.get('market_baseline_comparable') is False):
            reasons.append('conditional_or_ternary_forecast_not_unconditional_token_value')
        if not _number(f.get('probability')):reasons.append('finite_independent_probability_required')
        try:
            _descriptor, group, tags = canonical_event(f)
            row['correlation'].update(canonical_group_id=group, dependency_tags=tags)
            if f['id'] in verified:cohorts[cohort_key(f, group)].append(row)
        except (KeyError, ValueError, TypeError, OverflowError) as error:reasons.append(str(error)[:160])
        if not reasons:
            row['gross_probability_gap_to_ask'] = f['probability']-b.asks[0].price
            # A new decision book does not change any original forecast fields.
            decision = {**f, 'book': b.model_dump(mode='json'), 'book_id': b.id,
                        'book_sha256': digest(b.model_dump(mode='json')), 'market': m.model_dump(mode='json')}
            costs, verifier, reason = _cost_context(f, study, decision, fee_quotes, now)
            if reason:reasons.append(reason)
            else:
                diagnostic = executable_diagnostic(decision, evaluated_at=now, forecast_verified=True,
                                                   cost_evidence=costs, cost_verifier=verifier)
                reasons += diagnostic['reasons']
                row['estimated_after_cost_edge'] = diagnostic['estimated_net_edge']
                row['capacity'] = diagnostic['capacity']
                row['fee_and_cost_evidence_sha256'] = digest(costs)
                if diagnostic['status'] == 'qualified_research_diagnostic':
                    row['estimated_after_cost_edge'] = diagnostic['estimated_net_edge']
                    row['standard_probe'] = _probe(b, decision, costs)
                    if row['standard_probe']['conservative_expected_net_value_usd'] is not None:
                        row['status'] = 'qualified_research_diagnostic'
                        row['confidence_status'] = 'independently_replayed_calibration_and_costs_research_only'
                    else:reasons.append('standard_position_minimum_lot_or_notional_not_supported')
        if b and not row['capacity'] and f['token_id'] not in bad:
            row['capacity'] = capacity_scenarios({'market_id': f['market_id'], 'token_id': f['token_id'],
                'book_id': b.id, 'book_sha256': digest(b.model_dump(mode='json')), 'evaluated_at': now.isoformat(),
                'end_time': None, 'research_qualified': False}, b)
        row['reasons'] = sorted(set(reasons))
        rejected.update(row['reasons'])
        findings.append(row)
    ranking = sorted((r for r in findings if r['status'] == 'qualified_research_diagnostic'),
                     key=lambda r: (-r['standard_probe']['conservative_expected_net_value_usd'], r['id']))
    for i, row in enumerate(ranking, 1):row['finding_rank'] = i
    comparisons = []
    for key, rows in sorted(cohorts.items()):
        if len(rows) < 2 or len({r['model_id'] for r in rows}) != len(rows):continue
        ps = [r['forecast_probability'] if r['forecast_probability'] is not None else r['expected_payout'] for r in rows]
        if not all(_number(p) for p in ps):continue
        comparisons.append({'cohort_id': key, 'canonical_group_id': rows[0]['correlation']['canonical_group_id'],
                            'forecast_ids': sorted(r['forecast_id'] for r in rows),
                            'probability_or_expected_payout_range': max(ps)-min(ps), 'probability_semantics': rows[0]['probability_semantics'],
                            'independent_confirmation_count': None,
                            'ensemble_probability': None, 'scope': 'identical original event/time/target/book; agreement is not calibrated skill or independent evidence', **AUTHORITY})
    result = {'schema_version': VERSION, 'as_of': now.isoformat(),
            'policy': {'forecast_max_age_seconds': FORECAST_MAX_AGE_SECONDS, 'book_max_age_seconds': 15,
                       'max_spread': .05, 'minimum_net_edge': .03, 'research_probe_max_usd': 5,
                       'maximum_findings': MAX_FINDINGS, 'qualification_thresholds_relaxed': False},
            'counts': {'original_forecasts_bound': len(found), 'findings_evaluated': len(findings),
                       'deferred_due_to_bounded_evaluation': deferred, 'qualified_research_findings': len(ranking),
                       'execution_authorized': 0, 'reviewed_canonical_groups': len({r['correlation']['canonical_group_id'] for r in findings if r['correlation']['canonical_group_id']}),
                       'statistically_independent_resolved_events': 0},
            'findings': findings, 'rankings': [r['id'] for r in ranking], 'comparisons': comparisons,
            'rejections': dict(rejected), 'sii': {'qualified_pairs': 0, 'incremental_value': None,
                       'reason': 'independent causal persistence and paired verified outcomes not supplied; relationship context has no authority'},
            'portfolio': {'expected_value': None, 'allocation': None,
                          'reason': 'never sum shared books, event dependencies or correlated evidence; independent portfolio risk/admission approval required'},
            'realized_simulated_pnl': None, 'drawdown': None,
            'limitations': ['Current prices are observations, never independent forecasts',
                'No hypothetical sweep is a fill, settled return or evidence of profitability',
                'Fresh books never redate original forecasts or establish independent evidence',
                'Large-capital scenarios are hypothetical and cannot increase approved account sizing'], **AUTHORITY}

    size = 0
    for chunk in json.JSONEncoder(allow_nan=False, separators=(',', ':')).iterencode(result):
        size += len(chunk.encode())
        if size > 8*1024**2:raise ValueError('bounded_findings_report_byte_budget_exceeded')
    return result
