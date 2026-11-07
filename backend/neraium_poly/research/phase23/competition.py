"""Prospective research competition; pending predictions never establish skill.

Original sources and enrollments remain in the managed append-only archive. This
pure projection validates chronology and provenance, then requires a separately
replayed terminal proof before scoring. Assertions on a supplied row are not proof.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite, log, sqrt
from urllib.parse import urlsplit

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase13.contracts import SourceArtifact
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint

AUTHORITY = {'research_only': True, 'trading_authority': False, 'certification_authority': False,
             'experimental_admission_authority': False}
VERSION = 'phase23-research-competition-v1'


def _at(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('aware_competition_time_required')
    return value.astimezone(UTC)


def _prob(value):
    return type(value) in (int, float) and isfinite(value) and 0 <= value <= 1


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def challenger_definitions(*, declared_at):
    """Versioned falsifiable hypotheses, not seven approved probability models."""
    at = _at(declared_at).isoformat()
    hypotheses = {
        'independent-directional': ('Independent outcome forecasts improve paired Brier versus the contemporaneous market.',
                                   'Causal external evidence, exact rules and verified terminal outcomes'),
        'microstructure': ('Imbalance conditions predict subsequent executable repricing after crossing costs.',
                           'Native complete books, nonoverlapping causal windows and observed subsequent books'),
        'cross-market-consistency': ('Reviewed logical payoff constraints occasionally survive executable costs.',
                                     'Reviewed complete payoff sets, contemporaneous books and all-leg execution'),
        'event-repricing': ('Predecision external releases predict executable event repricing.',
                            'Authentic release availability, preregistered response horizon and observed books'),
        'evidence-updating': ('New independent information improves an unchanged-evidence forecast baseline.',
                             'Qualified independent source lineages and timestamped prior/posterior forecasts'),
        'sii-assisted': ('Persistent contextual relationship features add paired held-out predictive value.',
                        'Frozen challenger, prior relationship baseline and same-event same-cutoff control'),
        'ensemble': ('Chronologically trained combination improves independent held-out forecast accuracy.',
                     'Verified disjoint training events and independently calibrated, nonredundant model inputs'),
    }
    rows = []
    for name, (hypothesis, requirements) in hypotheses.items():
        row = {'model_id': name, 'version': VERSION, 'declared_at': at,
               'hypothesis': hypothesis, 'input_requirements': requirements,
               'failure_condition': 'No held-out improvement after dependence uncertainty and execution costs',
               'risk_assumptions': 'Existing capital, stops, admission and exposure limits unchanged',
               'performance_metrics': ['independent_events', 'paired_brier', 'log_loss', 'after_cost_edge'],
               'status': 'research_hypothesis', **AUTHORITY}
        rows.append({**row, 'enrollment_sha256': digest(row)})
    return rows


def _forecast(row, study, now):
    f = deepcopy(row)
    for key in ('id', 'event_id', 'market_id', 'token_id', 'model_version'):
        if not isinstance(f.get(key), str) or not 1 <= len(f[key]) <= 256:
            raise ValueError('bounded_forecast_identity_required')
    timestamp = _at(f['timestamp'])
    cutoff = _at(f['evidence_cutoff'])
    if not cutoff <= timestamp <= _at(study['available_at']) <= now:
        raise ValueError('prospective_causal_forecast_time_required')
    distribution = f.get('probability_semantics') == 'outcome_distribution'
    market_value = f.get('market_expected_payout') if distribution else f.get('market_probability')
    if not _prob(f.get('probability')) or not _prob(market_value):
        raise ValueError('finite_forecast_and_contemporaneous_baseline_required')
    if distribution:
        probs = f.get('outcome_probabilities', {})
        if (set(probs) != {'win','tie','loss'} or not all(_prob(v) for v in probs.values())
            or abs(sum(probs.values())-1)>1e-10 or abs(probs['win']-f['probability'])>1e-12
            or f.get('market_probability') is not None
            or abs(f.get('expected_payout', -1)-(probs['win']+.5*probs['tie']))>1e-12):
            raise ValueError('ternary_distribution_is_not_binary_market_probability')
    uncertainty = f.get('uncertainty', {})
    lower = f.get('lower_probability', uncertainty.get('lower_probability'))
    upper = f.get('upper_probability', uncertainty.get('upper_probability'))
    if not _prob(lower) or not _prob(upper) or not lower <= f['probability'] <= upper:
        raise ValueError('explicit_probability_uncertainty_required')
    if not _sha(f.get('rules_sha256')) or not _sha(f.get('model_sha256')):
        raise ValueError('versioned_model_and_resolution_rules_required')
    if f.get('trading_authority') is not False or f.get('research_only') is not True:
        raise ValueError('research_only_forecast_required')
    market_raw = f.get('market') or study.get('market')
    book_raw = f.get('book') or study.get('book')
    market = MarketSnapshot.model_validate(market_raw)
    book = OrderBookSnapshot.model_validate(book_raw)
    if (market.market_id != f['market_id'] or market.token_id != f['token_id']
        or market.event_id != f['event_id'] or book.market_id != market.market_id
        or book.token_id != market.token_id or book.source not in PUBLIC_BOOK_SOURCES
        or book.exchange != market.exchange or market.exchange != 'polymarket'
        or market.source != 'https://gamma-api.polymarket.com' or market.status != 'active'
        or not market.end_time or timestamp >= market.end_time
        or not market.timestamp <= market.available_at <= cutoff
        or not market.resolution_source or not market.resolution_rules
        or sha256(market.resolution_rules.encode()).hexdigest() != f['rules_sha256']
        or not assess_book(book, timestamp, max_spread=.05, expected_token=f['token_id']).healthy):
        raise ValueError('original_forecast_market_rule_book_binding_required')
    if abs(market_value-(book.bids[0].price+book.asks[0].price)/2) > 1e-12:
        raise ValueError('same_timestamp_book_baseline_required')
    if f.get('book_sha256') is not None and f['book_sha256'] != digest(book.model_dump(mode='json')):
        raise ValueError('original_book_hash_required')
    evidence = [DomainEvidence.model_validate(e) for e in study.get('evidence', [])]
    selected = {e.id: e for e in evidence}
    ids = f.get('evidence_ids', [])
    lineages = set()
    if distribution:
        reference = f.get('source_reference', {})
        artifacts = [SourceArtifact.model_validate(a) for a in reference.get('artifacts', [])]
        if (not artifacts or len(artifacts)>16 or reference.get('availability_basis') != 'actual_original_retrieval'
            or not _sha(reference.get('manifest_sha256')) or ids != [reference['manifest_sha256']]
            or not reference.get('source_lineage') or not f.get('sports_mapping')
            or any(max(a.available_at,a.retrieved_at)>cutoff or a.quality!='qualified'
                or not _sha(a.content_sha256) or urlsplit(a.source_url).scheme!='https' for a in artifacts)):
            raise ValueError('causal_native_sports_source_reference_required')
        lineages.add(reference['source_lineage'])
        ids = []
    elif not ids or len(set(ids)) != len(ids) or any(i not in selected for i in ids):
        raise ValueError('bound_external_evidence_required')
    for identity in ids:
        e = selected[identity]
        host = urlsplit(e.source).hostname
        if (not host or urlsplit(e.source).scheme != 'https'
            or host == 'polymarket.com' or host.endswith('.polymarket.com')
            or e.qualification != 'qualified_research' or not e.independent_of_polymarket
            or digest(e.payload) != e.content_sha256
            or max(e.timestamp, e.available_at, e.retrieved_at) > cutoff):
            raise ValueError('causal_independent_source_payload_required')
        lineages.add(e.provider+':'+e.source_id)
    f.update(model_id=f.get('model_id', f['model_version']), timestamp=timestamp.isoformat(),
             evidence_cutoff=cutoff.isoformat(), source_lineages=sorted(lineages),
             event_end_time=market.end_time.isoformat(), book_sha256=digest(book.model_dump(mode='json')))
    return f


def _score(p, y):
    clipped = min(1-1e-12, max(1e-12, p))
    return (p-y)**2, -(y*log(clipped)+(1-y)*log(1-clipped))


def build_leaderboard(studies, outcomes=(), *, as_of, outcome_verifier=None):
    """Separate genuine pending forecasts, historical exploration and verified scores.

    A verifier must independently replay each terminal outcome and return the exact
    forecast/rules/token/event binding plus reviewed dependency group. No callback
    means no scored events, even if an input claims ``verified=True``. One earliest
    forecast per model/dependency group is selected before outcome scoring.
    """
    now = _at(as_of)
    if not isinstance(studies, (tuple, list)) or len(studies) > 1000 or not isinstance(outcomes, (tuple, list)) or len(outcomes) > 10000:
        raise ValueError('bounded_competition_inputs_required')
    rejected, forecasts, seen, models = Counter(), [], {}, defaultdict(list)
    historical = 0
    enrollments, conflicts = {}, set()
    for study in studies:
        if not isinstance(study, dict) or not study.get('enrollment'):
            continue
        try:
            state = unpack_checkpoint(study['checkpoint'])
            definitions = study['enrollment']
            identity = study['enrollment_id']
            if (not 1 <= len(definitions) <= 32 or digest(state) != study['checkpoint_sha256']
                or not _sha(state.get('code_sha256'))
                or identity != digest(['phase23-prospective-research', definitions, state['code_sha256']])
                or _at(study['available_at']) > now):
                raise ValueError('immutable_enrollment_content_binding_required')
            spec = {'definitions':definitions, 'declared_at':study['available_at']}
            if identity in enrollments and enrollments[identity] != spec:
                conflicts.add(identity)
                raise ValueError('conflicting_immutable_enrollment')
            enrollments[identity] = spec
        except (ValueError, KeyError, TypeError) as error:
            rejected[str(error)[:120] if isinstance(error, ValueError) else 'malformed_enrollment'] += 1
    for identity in conflicts:
        enrollments.pop(identity, None)
    forecast_conflicts = set()
    for study in studies:
        if not isinstance(study, dict):
            rejected['structured_study_required'] += 1
            continue
        if study.get('operation') in {'historical_replay', 'historical_exploratory'}:
            historical += 1
            continue
        supplied = study.get('forecasts', [study['forecast']] if study.get('forecast') else [])
        if not isinstance(supplied, (list, tuple)) or len(supplied) > 128:
            rejected['bounded_forecast_batch_required'] += 1
            continue
        for row in supplied:
            try:
                spec = enrollments.get(row.get('enrollment_id'))
                if spec is None or _at(spec['declared_at']) > _at(row['evidence_cutoff']):
                    raise ValueError('prior_immutable_model_enrollment_required')
                definition = next((d for d in spec['definitions'] if d.get('model_id') == row.get('model_id')), None)
                if (definition is None or definition.get('model_version') != row.get('model_version')
                    or definition.get('model_sha256') != row.get('model_sha256')
                    or definition.get('trading_authority') is not False):
                    raise ValueError('predeclared_model_identity_required')
                f = _forecast(row, study, now)
                identity = f['id']
                content = digest(row)
                if identity in seen:
                    if seen[identity] != content:
                        forecast_conflicts.add(identity)
                        raise ValueError('conflicting_immutable_forecast_identity')
                    rejected['duplicate_forecast'] += 1
                    continue
                seen[identity] = content
                forecasts.append(f)
            except (ValueError, KeyError, TypeError) as error:
                rejected[str(error)[:120] if isinstance(error, ValueError) else 'malformed_forecast'] += 1
    forecasts = [f for f in forecasts if f['id'] not in forecast_conflicts]
    by_id = {f['id']: f for f in forecasts}
    proofs, proof_conflicts = {}, set()
    for outcome in outcomes:
        try:
            f = by_id.get(outcome.get('forecast_id'))
            if f and f.get('probability_semantics') == 'outcome_distribution':
                raise ValueError('verified_ternary_outcome_and_comparable_market_distribution_required')
            if f is None or not callable(outcome_verifier):
                raise ValueError('independent_outcome_replay_required')
            try:
                proof = outcome_verifier(deepcopy(outcome), deepcopy(f))
            except Exception:  # noqa: BLE001 - failed external replay cannot create a label
                raise ValueError('independent_outcome_replay_failed') from None
            if (not isinstance(proof, dict) or proof.get('verified') is not True
                or any(proof.get(k) != f[k] for k in ('event_id', 'market_id', 'token_id', 'rules_sha256'))
                or proof.get('forecast_id') != f['id'] or type(proof.get('outcome')) is not int
                or proof['outcome'] not in (0, 1) or not proof.get('reviewed_dependency_group')
                or not _sha(proof.get('evidence_sha256'))
                or not _at(f['timestamp']) < _at(proof['resolved_at']) <= _at(proof['available_at']) <= now):
                raise ValueError('exact_verified_terminal_event_binding_required')
            if f['id'] in proofs and proofs[f['id']] != proof:
                proof_conflicts.add(f['id'])
                raise ValueError('conflicting_verified_outcome')
            proofs[f['id']] = proof
        except (ValueError, KeyError, TypeError) as error:
            rejected[str(error)[:120] if isinstance(error, ValueError) else 'malformed_outcome'] += 1
    for identity in proof_conflicts:
        proofs.pop(identity, None)
    for f in forecasts:
        models[f['model_version']].append(f)
    rows = []
    for model, fs in sorted(models.items()):
        selected = {}
        for f in sorted(fs, key=lambda x: (x['timestamp'], x['id'])):
            if f['id'] in proofs:
                selected.setdefault(proofs[f['id']]['reviewed_dependency_group'], f)
        losses = [_score(f['probability'], proofs[f['id']]['outcome']) for f in selected.values()]
        baselines = [_score(f['market_probability'], proofs[f['id']]['outcome']) for f in selected.values()]
        n = len(losses)
        improvements = [b[0]-m[0] for m,b in zip(losses, baselines, strict=True)]
        mean = sum(improvements)/n if n else None
        # Simultaneous Hoeffding bound across all compared models, on event-group
        # differences in [-1,1]. Conservative and descriptive, not certification.
        radius = sqrt(2*log(max(1,len(models))*40)/n) if n else None
        metrics = {'brier':sum(x[0] for x in losses)/n,'log_loss':sum(x[1] for x in losses)/n,
                   'market_brier':sum(x[0] for x in baselines)/n,'market_log_loss':sum(x[1] for x in baselines)/n,
                   'paired_brier_improvement':mean,'paired_brier_improvement_95_simultaneous_interval':[max(-1,mean-radius),min(1,mean+radius)]} if n else None
        rows.append({'model_version':model,'prospective_forecasts':len(fs),
            'pending_forecasts':sum(f['id'] not in proofs for f in fs),'unreviewed_parent_events':len({f['event_id'] for f in fs}),
            'independent_verified_events':n,'category':'prospective_verified' if n else 'prospective_unresolved',
            'metrics':metrics,'score_semantics':('ternary_outcome_distribution_requires_comparable_market_baseline' if any(f.get('probability_semantics')=='outcome_distribution' for f in fs) else 'binary_event_probability'),'calibration_status':'insufficient_independent_events' if n < 100 else 'research_evaluation_only',
            'statistically_supported_brier_improvement':bool(n >= 100 and mean-radius > 0),
            'profitability_rank':None,'net_hypothetical_executable_edge':None,'simulated_realized_pnl':None,
            'drawdown':None,'source_lineages':sorted({v for f in fs for v in f['source_lineages']}), **AUTHORITY})
    overlaps = []
    for i,left in enumerate(rows):
        for right in rows[i+1:]:
            shared = sorted(set(left['source_lineages']) & set(right['source_lineages']))
            if shared:
                overlaps.append({'left':left['model_version'],'right':right['model_version'],'shared_source_lineages':shared,
                                 'independent_confirmations':False})
    return {'schema_version':VERSION,'evaluated_at':now.isoformat(),'leaderboard':rows,
        'counts':{'historical_exploratory_studies':historical,'prospective_forecasts':len(forecasts),
                  'pending_forecasts':sum(f['id'] not in proofs for f in forecasts),
                  'native_parent_events':len({f['event_id'] for f in forecasts}),
                  'independent_verified_groups':len({p['reviewed_dependency_group'] for p in proofs.values()}),
                  'certified_execution_authorized_challengers':0},
        'rejections':dict(rejected),'shared_lineage_models':overlaps,
        'sii_incremental_value':None,'ensemble_status':'withheld_until_independent_chronological_calibration',
        'ranking_scope':'Verified paired forecast scores only; pending models never ranked by profitability',
        'certified_requirements':{'training_independent_events':100,'heldout_independent_events':100}, **AUTHORITY}


def aggregate_capacity(opportunities, *, reviewed_disjoint_groups=()):
    """Conservative per-parent capacity; summation needs reviewed disjoint groups.

    Every row must carry a native phase18 capacity_scenarios result. The projection
    never converts displayed liquidity into profit or an authorized position.
    """
    if not isinstance(opportunities,(tuple,list)) or len(opportunities)>1000:
        raise ValueError('bounded_capacity_rows_required')
    parents, rejected = {}, Counter()
    for row in opportunities:
        capacity = row.get('capacity',{})
        if not row.get('event_id') or capacity.get('status') not in {'liquidity_only_unqualified','qualified_research_capacity'}:
            rejected['native_capacity_and_parent_required'] += 1
            continue
        for scenario in capacity.get('scenarios',[]):
            key=(row['event_id'],scenario['hypothetical_bankroll'])
            value=scenario['modeled_entry_notional']
            if type(value) not in (int,float) or not isfinite(value) or value<0:
                raise ValueError('finite_native_capacity_required')
            if key not in parents or parents[key]['principal']<value:
                parents[key]={'event_id':row['event_id'],'capital':key[1], 'principal':value,
                    'dependency_group':row.get('reviewed_dependency_group'), 'market_id':row.get('market_id'),
                    'edge_qualified':capacity['status']=='qualified_research_capacity'}
    reviewed=set(reviewed_disjoint_groups)
    by_capital=defaultdict(list)
    for item in parents.values():by_capital[item['capital']].append(item)
    result=[]
    for capital,items in sorted(by_capital.items()):
        groups={}
        for row in items:
            group=row['dependency_group']
            if group in reviewed:groups[group]=max(groups.get(group,0),row['principal'])
        result.append({'hypothetical_bankroll':capital,'parent_capacity_rows':len(items),
            'largest_parent_entry_notional':max(x['principal'] for x in items),
            'reviewed_disjoint_group_liquidity_sum':sum(groups.values()) if groups else None,
            'reviewed_group_count':len(groups),'profitable_deployable_capital':None,
            'hypothetical20percent_portfolio_limit':.2*capital,
            'liquidity_allocation_after_aggregate_cap':min(sum(groups.values()),.2*capital) if groups else None,
            'unreviewed_parents_not_summed':sum(x['dependency_group'] not in reviewed for x in items)})
    return {'scenarios':result,'rejections':dict(rejected),
        'scope':'Per-parent maximum; only explicitly reviewed disjoint groups can be summed; liquidity is not profit', **AUTHORITY}
