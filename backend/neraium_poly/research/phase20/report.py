"""Read-only bounded native replay; no labels inferred from quote marks."""
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase19.qualification import (
    _original,
    qualification_readiness,
    replay_event_forecast,
)
from neraium_poly.research.phase21.outcomes import replay_crypto_outcome


def evaluate_archive(directory, *, training_end, heldout_start, as_of=None, limit=1000):
    as_of = as_of or datetime.now(UTC)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('bounded forecast study limit required')
    directory = Path(directory).absolute()
    with ReadonlyArchive(directory, max_query_bytes=128*1024**2) as archive:
        rows = archive.latest('EventProbabilityStudy', limit)
        pairs = archive.latest('PairedForecastStudy', min(limit, 128))
        early = archive.latest('EventResolutionStudy', min(limit, 128))
        total = archive._catalog_rows('SELECT count(*) AS n FROM records WHERE kind=?',
                                     ('EventProbabilityStudy',))[0]['n']
    rows += [r for r in early if r.get('operation') == 'outcome_check']
    originals = {r['forecast']['id']: r for r in rows
                 if r.get('operation') == 'forecast_scan' and r.get('forecast')}
    outcome_replays = {}
    for row in rows:
        if row.get('operation') != 'outcome_check' or not row.get('outcome'):
            continue
        original = originals.get(row.get('forecast', {}).get('id'))
        if original:
            outcome_replays[row['id']] = replay_crypto_outcome(row, original,
                evidence_root=directory/'phase18-resolution-evidence', as_of=as_of)
    report = qualification_readiness(rows, as_of=as_of, training_end=training_end,
        heldout_start=heldout_start, verify_forecast=replay_event_forecast,
        verify_outcome=lambda row, _original: outcome_replays.get(row['id'], {}).get('verified') is True)
    report['schema_version'] = 'phase20-forecast-evaluation-v1'
    report['archive_scope'] = {'total_studies': total, 'included_studies': len(rows),
        'bounded_tail': total > limit, 'native_outcome_records_replayed': len(outcome_replays),
        'count_scope': 'total_studies is P18 only; included_studies also includes additive early native-check attempts',
        'early_native_attempt_records_included': sum(r.get('operation') == 'outcome_check' for r in early)}
    report['outcome_replays'] = outcome_replays
    report['early_reference_checks'] = len(early)
    report['outcome_rule'] = 'Exact immediate-YES final-minute hit permits a native check; every label still requires finalized settlement proof'
    completed = set()
    for study in originals.values():
        try:
            _forecast, market, _book, _evidence = _original(study)
            if market.end_time <= as_of:
                completed.add(_forecast.id)
        except (KeyError, TypeError, ValueError):
            pass  # qualification_readiness already preserves the structured rejection
    verified = {v['forecast_id'] for v in outcome_replays.values() if v.get('verified') is True}
    report['completed_reference_windows'] = len(completed)
    report['matured_forecasts'] = len(completed | verified)
    report['maturity_count_scope'] = 'completed reference windows or independently verified early terminal labels; reference hits alone never counted as finalized'
    report['pending_resolution_rule'] = 'completed-minute YES condition OR completed no-hit reference day, PLUS exact native finality; no price labels'
    report['sii_comparison'] = {'status': 'unmeasured', 'brier_improvement': None,
        'log_loss_improvement': None, 'after_cost_edge': None, 'sii_in_trading_path': False,
        'reason': 'frozen trained SII challenger, causal relationship evidence and verified event-disjoint outcomes required',
        'latest_prospective_state': pairs[0]['checkpoint'] if pairs else None,
        'scope': 'current research policy has no challenger; no retrospective SII probabilities synthesized'}
    return report
