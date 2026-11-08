"""Volume-aware research economics, separate from certified admission.

Unknown costs/calibration never become validated EV. Original forecasts remain
immutable; a fresh book cannot redate an old hypothesis. No three-cent gate is
used in this module and no result grants execution authority.
"""
import json
import math
from collections import Counter

from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import AUTHORITY, at, bound_forecasts
from neraium_poly.research.phase27.findings import _current, _expected_payout, build_findings

VERSION = 'phase28-volume-economic-findings-v1'
NON_DATA_REASONS = {
    'independent_exact_calibration_and_cost_replay_required',
    'expected_payout_requires_separate_calibrated_token_valuation_protocol',
    'native_reference_and_fallback_compatibility_not_independently_validated',
    'conditional_or_ternary_forecast_not_unconditional_token_value',
    'large_spread',
}
COST_FIELDS = ('effective_entry_fee_rate', 'slippage_per_share',
               'latency_adverse_selection_per_share', 'capital_lockup_cost_per_share',
               'settlement_risk_cost_per_share', 'settlement_cost_per_share')


def _number(value, low=0., high=1.):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _proof(bundle, f, study, book, now):
    if not isinstance(bundle, dict) or not isinstance(bundle.get('evidence'), dict) or not callable(bundle.get('verifier')):
        return None, ['independent_exact_cost_replay_required']
    e = bundle['evidence']
    try:
        if (e.get('forecast_id') != f['id'] or e.get('original_forecast_sha256') != digest(f)
                or e.get('original_study_sha256') != digest(study)
                or e.get('book_sha256') != digest(book.model_dump(mode='json'))
                or at(e['decision_at']) != now or at(e['available_at']) > now
                or e.get('cost_model') != 'phase28-effective-total-costs-v1'
                or any(not _number(e.get(k)) for k in COST_FIELDS)
                or e.get('native_fee_verified') is not True):
            raise ValueError('exact_causal_native_effective_cost_binding_required')
        decision = {**f, 'book': book.model_dump(mode='json'), 'book_id': book.id,
                    'book_sha256': digest(book.model_dump(mode='json'))}
        proof = bundle['verifier'](e, decision, as_of=now)
        if not isinstance(proof, dict) or proof.get('verified') is not True:
            raise ValueError('independent_cost_source_replay_failed')
        return e, []
    except Exception as error:  # noqa: BLE001 - unavailable proof cannot qualify economics
        return None, [str(error)[:160] if isinstance(error, ValueError) else 'cost_replay_unavailable:'+type(error).__name__]


def _qualified_evidence(costs, f):
    if costs is None:return False
    try:
        return (costs.get('calibration_verified') is True
                and costs.get('event_disjoint_calibration_verified') is True
                and costs.get('settlement_rule_compatibility_verified') is True
                and costs.get('unconditional_contract_value_verified') is True
                and isinstance(costs.get('calibration_artifact_sha256'), str)
                and len(costs['calibration_artifact_sha256']) == 64
                and all(c in '0123456789abcdef' for c in costs['calibration_artifact_sha256'])
                and at(costs['calibration_cutoff']) <= at(f['timestamp']))
    except (KeyError, ValueError, TypeError):return False


def _economics(value):
    if not isinstance(value, dict):return None
    return {'quantity': value.get('quantity'), 'principal': value.get('principal'),
            'entry_fees': value.get('entry_fees'), 'slippage_cost': value.get('slippage_cost'),
            'settlement_cost': value.get('settlement_cost'), 'capital_required': value.get('capital_required'),
            'point_expected_gross_profit': value.get('expected_gross_profit'),
            'point_expected_net_profit': value.get('expected_net_profit'),
            'conservative_expected_net_profit': value.get('lower_net_profit'),
            'return_on_capital': value.get('return_on_capital')}


def _portfolio(rows):
    """Conservative non-additive greedy survey, never account allocation."""
    used_books, used_groups, used_tags, selected = set(), set(), set(), []
    rejected = {}
    for row in rows:
        c = row['correlation']; group = c.get('canonical_group_id'); tags = set(c.get('dependency_tags', []))
        if (not group or row['book_id'] in used_books or group in used_groups or tags & used_tags):
            rejected[row['id']] = 'shared_book_event_or_dependency_capacity_not_additive'
            continue
        selected.append(row['id']); used_books.add(row['book_id']); used_groups.add(group); used_tags.update(tags)
    return {'survey_selection': selected, 'excluded': rejected, 'portfolio_expected_profit': None,
            'correlation_adjusted_contribution': None,
            'reason': 'standalone USD EV ranking is not joint risk approval or proof of independent events', **AUTHORITY}


def build_economic_findings(studies, frame, *, as_of, verified_forecast_ids=(), fee_quotes=None, native_fee_observations=None, included_forecast_ids=None):
    """Rank conservative USD expected profit; preserve smaller-margin scenarios.

    phase27 is used only for source/time/identity taxonomy with *no* cost bundle,
    so its legacy three-cent diagnostic/probe is never entered. Research crossing
    costs are represented by actual ask levels, not a second spread deduction.
    """
    from .execution import analyze_depth

    now = at(as_of)
    _raw, markets, books, bad = _current(frame, now)
    originals, _rejected = bound_forecasts(studies, as_of=now)
    if included_forecast_ids is not None:
        included=set(included_forecast_ids)
        originals={k:v for k,v in originals.items() if k in included}
    if len(originals) > 128:raise ValueError('bounded_phase28_forecast_universe_exceeded')
    base = build_findings(studies, frame, as_of=now, verified_forecast_ids=verified_forecast_ids, fee_quotes=None)
    rows = []; rejected = Counter(); verified = set(verified_forecast_ids)
    for previous in base['findings']:
        if previous['forecast_id'] not in originals:continue
        row = dict(previous); source = originals[row['forecast_id']]; f, study = source['forecast'], source['study']
        b = books.get(row['token_id']); m = markets.get(row['token_id']); reasons = [x for x in previous['reasons'] if x not in NON_DATA_REASONS]
        row.update(id=digest([VERSION, previous['id']]), version=VERSION, certified_screening_status=previous['status'],
            certified_book_screening_compatible=previous['book_qualified_for_current_observation'],
            certified_minimum_edge_unchanged=.03, research_minimum_per_share_edge=None,
            execution_analysis=None, economics=None, scenario_expected_gross_profit=None,
            scenario_expected_net_profit=None, conservative_expected_net_profit=None,
            maximum_supported_quantity=None, capital_required=None, return_on_capital=None,
            break_even_entry_fee_rate_before_other_costs=None,
            scenario_rank=None, economic_rank=None, qualified_research=False, shadow_eligible=False,
            strategy_eligibility=[], strategy_rejections={}, status='withheld', cost_assumptions=None, price_levels=None,
            confidence_status='unvalidated_research', validated_profitability=False,
            correlation_adjusted_portfolio_contribution=None, execution_authorized=False)
        row['finding_rank'] = None; row['estimated_after_cost_edge'] = None
        row['standard_probe'] = None; row['capacity'] = None
        row['certified_admission_required'] = True
        row['native_market_constraints'] = {'minimum_order_size': m.min_order_size if m else None, 'price_tick_size': m.tick_size if m else None}
        value = _expected_payout(f)
        semantics = f.get('probability_semantics')
        if semantics == 'binary_event_probability' and _number(f.get('probability')):
            value = f['probability']
        if value is None:reasons.append('supported_contract_payout_semantics_required')
        conditional = bool(f.get('target_conditioning') or f.get('conditioning')
            or f.get('unconditional_contract_probability') is False or f.get('market_baseline_comparable') is False)
        row['valuation_scope'] = 'conditional_model_scenario' if conditional else 'independent_model_scenario'
        if b is not None:
            # Wide spreads are measured market conditions in research, not a
            # fabricated discount or permission to bypass certified spread rules.
            quote = assess_book(b, now, max_spread=1., expected_token=f['token_id'])
            reasons += list(quote.reasons)
            if (quote.healthy and row['settlement_risk']['rules_match_current_market']
                    and b.source in PUBLIC_BOOK_SOURCES and b.exchange == 'polymarket'
                    and b.market_id == f['market_id'] and b.token_id == f['token_id'] and f['token_id'] not in bad
                    and 0 <= (now-b.available_at).total_seconds() <= 15
                    and len({x.price for x in b.asks}) == len(b.asks)
                    and len({x.price for x in b.bids}) == len(b.bids)):
                row['book_qualified_for_current_observation'] = True
                row['executable_ask'], row['executable_bid'] = b.asks[0].price, b.bids[0].price
        if not reasons and b is not None and value is not None:
            row['price_levels'] = {'asks': [x.model_dump(mode='json') for x in b.asks],
                                   'bids': [x.model_dump(mode='json') for x in b.bids]}
            bundle = fee_quotes.get(f['id']) if isinstance(fee_quotes, dict) else None
            costs, cost_reasons = _proof(bundle, f, study, b, now)
            row['cost_evidence'] = json.loads(json.dumps(costs, allow_nan=False)) if costs is not None else None
            row['fee_and_cost_evidence_sha256'] = digest(costs) if costs is not None else None
            lower = f.get('lower_probability'); upper = f.get('upper_probability')
            interval_valid = _number(lower) and _number(upper) and lower <= value <= upper
            if not interval_valid:lower = upper = None
            extra = sum(costs[k] for k in ('slippage_per_share', 'latency_adverse_selection_per_share',
                                          'capital_lockup_cost_per_share', 'settlement_risk_cost_per_share')) if costs else 0.
            analysis = analyze_depth(b, as_of=now, expected_payout=value,
                lower_payout=lower, upper_payout=upper,
                fee_rate=costs['effective_entry_fee_rate'] if costs else None,
                slippage_per_share=extra, settlement_cost_per_share=costs['settlement_cost_per_share'] if costs else None)
            row['execution_analysis'] = analysis
            row['maximum_supported_quantity'] = analysis['maximum_supported_quantity']
            row['cost_assumptions'] = {'effective_entry_fee_rate': costs['effective_entry_fee_rate'] if costs else None,
                'settlement_cost_per_share': costs['settlement_cost_per_share'] if costs else None,
                'slippage_per_share': extra, 'latency_liquidity_fraction': .1,
                'source_verified': costs is not None, 'spread_paid_once_through_actual_asks': True,
                'unknown_nonfee_costs_are_not_zero_claims': costs is None}
            point = analysis.get('maximum_point_profit') or analysis.get('maximum_gross_profit')
            row['economics'] = _economics(point)
            if row['economics']:
                row['scenario_expected_gross_profit'] = row['economics']['point_expected_gross_profit']
                row['scenario_expected_net_profit'] = row['economics']['point_expected_net_profit']
                row['capital_required'] = row['economics']['capital_required']
                row['return_on_capital'] = row['economics']['return_on_capital']
                principal = row['economics']['principal']
                gross = row['scenario_expected_gross_profit']
                if _number(principal, 1e-12, 1e15) and _number(gross, 0, 1e15):
                    row['break_even_entry_fee_rate_before_other_costs'] = gross/principal
            row['status'] = 'modeled_economics_unvalidated'
            row['confidence_status'] = 'conditional_unvalidated_scenario' if conditional else 'unvalidated_model_scenario'
            evidence_valid = _qualified_evidence(costs, f)
            conservative = analysis.get('maximum_conservative_profit')
            supported = isinstance(conservative, dict) and _number(conservative.get('lower_net_profit'), 1e-12, 1e15)
            minimum = m.min_order_size if m is not None else None
            lot_ok = (supported and _number(minimum, 1e-9, 1e12)
                      and conservative['quantity']+1e-9 >= minimum)
            if (evidence_valid and f['id'] in verified and not conditional and interval_valid and supported and lot_ok):
                row['qualified_research'] = True; row['shadow_eligible'] = True
                row['status'] = 'conservative_positive_research'; row['confidence_status'] = 'independently_replayed_research_evidence'
                row['economics'] = _economics(conservative)
                row['conservative_expected_net_profit'] = conservative['lower_net_profit']
                row['capital_required'] = conservative['capital_required']; row['return_on_capital'] = conservative['return_on_capital']
                row['strategy_eligibility'] = ['small_edge']
                independent = costs.get('independent_evidence_lineages')
                if (upper-lower <= .10+1e-9 and costs.get('independent_evidence_convergence_verified') is True
                        and isinstance(independent, list) and len(independent) >= 2
                        and all(isinstance(x, str) and x for x in independent) and len(set(independent)) == len(independent)):
                    row['strategy_eligibility'].append('high_conviction')
                else:row['strategy_rejections']['high_conviction'] = 'independent_evidence_convergence_and_uncertainty_not_qualified'
                row['strategy_rejections'].update(cross_market='independent_logical_constraint_and_multileg_execution_proof_required',
                                                  ensemble='independently_validated_ensemble_model_required')
            else:
                reasons += cost_reasons
                if not evidence_valid:reasons.append('causal_calibration_settlement_and_unconditional_value_proof_required')
                if conditional:reasons.append('conditional_model_scenario_not_validated_unconditional_value')
                if not interval_valid:reasons.append('supported_uncertainty_interval_required')
                if not supported:reasons.append('positive_conservative_expected_dollar_profit_not_established')
                elif not lot_ok:reasons.append('native_minimum_order_quantity_not_supported')
        from neraium_poly.research.phase29.economics import diagnostic
        row['pipeline'] = diagnostic(f, m, b, row, as_of=now,
            native_fee=(native_fee_observations or {}).get(f['token_id']))
        row['reasons'] = sorted(set(reasons)); rejected.update(row['reasons']); rows.append(row)
    qualified = sorted((r for r in rows if r['qualified_research']),
                       key=lambda r: (-r['conservative_expected_net_profit'], r['id']))
    exploratory = sorted((r for r in rows if _number(r.get('scenario_expected_gross_profit'), 1e-12, 1e15)),
                         key=lambda r: (-r['scenario_expected_gross_profit'], r['id']))
    for rank, row in enumerate(qualified, 1):row['economic_rank'] = rank
    for rank, row in enumerate(exploratory, 1):row['scenario_rank'] = rank
    from neraium_poly.research.phase29.economics import stage_counts
    report = {'pipeline_counts': stage_counts(rows), 'schema_version': VERSION, 'as_of': now.isoformat(),
        'policy': {'research_minimum_per_share_edge': None, 'certified_minimum_edge_unchanged': .03,
                   'ranking_metric': 'independently_supported_conservative_expected_net_profit_USD',
                   'scenario_ranking_metric': 'unvalidated_model_expected_gross_profit_USD',
                   'latency_liquidity_fraction': .1, 'max_forecasts': 128,
                   'quantities_are_displayed_depth_capacity_not_fills': True},
        'counts': {'findings_evaluated': len(rows), 'qualified_research_findings': len(qualified),
                   'modeled_positive_gross_scenarios': len(exploratory), 'execution_authorized': 0,
                   'reviewed_canonical_groups': len({r['correlation']['canonical_group_id'] for r in rows if r['correlation']['canonical_group_id']}),
                   'statistically_independent_resolved_events': 0},
        'findings': rows, 'rankings': [r['id'] for r in qualified],
        'scenario_rankings': [r['id'] for r in exploratory], 'rejections': dict(rejected),
        'portfolio': _portfolio(qualified), 'comparisons': base['comparisons'], 'sii': base['sii'],
        'realized_simulated_pnl': None, 'drawdown': None, 'validated_profitability': False,
        'limitations': ['Model-implied USD profit is not verified realized profit',
                        'Unknown fees, settlement, calibration and dependence are not fabricated',
                        'Repeated models on shared books or events do not multiply available liquidity'], **AUTHORITY}
    if len(json.dumps(report, separators=(',', ':'), allow_nan=False).encode()) > 8*1024**2:
        raise ValueError('bounded_economic_findings_report_byte_budget_exceeded')
    return report


def combine_economic_reports(reports, *, as_of):
    """Merge same-decision streamed reports without retaining original studies.

    Duplicate forecasts never multiply capacity, ranks, counts or independent
    samples. Distinct forecasts on a shared book remain separate model findings
    but the non-additive portfolio survey excludes repeated source capacity.
    """
    now = at(as_of)
    if not isinstance(reports, (list, tuple)) or len(reports) > 128:
        raise ValueError('bounded_economic_report_batches_required')
    findings = {}; ids = {}; frame_hashes = set(); comparisons = {}
    for report in reports:
        if (report.get('schema_version') != VERSION or at(report['as_of']) != now
                or report.get('research_only') is not True or report.get('trading_authority') is not False
                or report.get('certification_authority') is not False or report.get('validated_profitability') is not False):
            raise ValueError('identical_research_only_decision_batches_required')
        for row in report.get('findings', []):
            if at(row['decision_at']) != now:
                raise ValueError('identical_economic_decision_times_required')
            identity = row['forecast_id']
            if row['id'] in ids and ids[row['id']] != identity:
                raise ValueError('conflicting_streamed_finding_identity')
            # Rankings are batch-relative. Normalize their position before
            # comparing a duplicate independently of batch partition shape.
            clean = {**row, 'economic_rank': None, 'scenario_rank': None}
            if identity in findings:
                previous = {**findings[identity], 'economic_rank': None, 'scenario_rank': None}
                if digest(previous) != digest(clean):raise ValueError('conflicting_streamed_forecast_economics')
            findings.setdefault(identity, clean); ids[row['id']] = identity
            frame_hashes.add(row['frame_sha256'])
            if len(findings) > 128:raise ValueError('bounded_streamed_findings_universe_exceeded')
        for pair in report.get('comparisons', []):comparisons.setdefault(digest(pair), pair)
    if len(frame_hashes) > 1:raise ValueError('identical_economic_decision_frame_required')
    rows = list(findings.values()); qualified = sorted((r for r in rows if r['qualified_research']),
        key=lambda r: (-r['conservative_expected_net_profit'], r['id']))
    exploratory = sorted((r for r in rows if _number(r.get('scenario_expected_gross_profit'), 1e-12, 1e15)),
        key=lambda r: (-r['scenario_expected_gross_profit'], r['id']))
    for rank, row in enumerate(qualified, 1):row['economic_rank'] = rank
    for rank, row in enumerate(exploratory, 1):row['scenario_rank'] = rank
    rejections = Counter(reason for row in rows for reason in row['reasons'])
    from neraium_poly.research.phase29.economics import stage_counts
    result = {'pipeline_counts': stage_counts(rows), 'schema_version': VERSION, 'as_of': now.isoformat(),
        'policy': {'research_minimum_per_share_edge': None, 'certified_minimum_edge_unchanged': .03,
                   'ranking_metric': 'independently_supported_conservative_expected_net_profit_USD',
                   'scenario_ranking_metric': 'unvalidated_model_expected_gross_profit_USD',
                   'latency_liquidity_fraction': .1, 'max_forecasts': 128,
                   'quantities_are_displayed_depth_capacity_not_fills': True,
                   'source_processing': 'original studies streamed one at a time; same-frame same-asof findings merged'},
        'counts': {'findings_evaluated': len(rows), 'qualified_research_findings': len(qualified),
                   'modeled_positive_gross_scenarios': len(exploratory), 'execution_authorized': 0,
                   'reviewed_canonical_groups': len({r['correlation']['canonical_group_id'] for r in rows if r['correlation']['canonical_group_id']}),
                   'statistically_independent_resolved_events': 0},
        'findings': rows, 'rankings': [r['id'] for r in qualified], 'scenario_rankings': [r['id'] for r in exploratory],
        'portfolio': _portfolio(qualified), 'comparisons': list(comparisons.values()), 'rejections': dict(rejections),
        'sii': {'qualified_pairs': 0, 'incremental_value': None,
                'reason': 'no independent causal feature/outcome-pair proof supplied; batch partitions are not experiments'},
        'realized_simulated_pnl': None, 'drawdown': None, 'validated_profitability': False,
        'limitations': ['Same event/model repetitions never become independent samples',
                        'Model estimates and displayed depth do not establish realized profitability',
                        'Portfolio survey does not authorize capital or fills'], **AUTHORITY}
    if len(json.dumps(result, separators=(',', ':'), allow_nan=False).encode()) > 8*1024**2:
        raise ValueError('bounded_economic_findings_report_byte_budget_exceeded')
    return result
