"""Bounded outcome-readiness diagnostics; never a settlement authorization.

Passing a calendar boundary is not a verified result. Source schema diagnostics
must not substitute for the existing exact-model/native/on-chain replay gates.
"""
import re
from collections import Counter
from datetime import timedelta

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

AUTHORITY = {'research_only': True, 'trading_authority': False, 'certification_authority': False}
REQUIRED_FINALITY_FIELDS = ('resolved_at', 'payouts', 'reporter', 'market_type', 'resolution_source',
                            'transaction_hash', 'extended_review', 'was_disputed', 'new_version_q',
                            'last_update_timestamp')


def outcome_reasons(result):
    """Preserve singular/list adapter reasons, bounded and without false labels."""
    candidates = [result.get('reason')]
    reasons = result.get('reasons')
    if isinstance(reasons, (list, tuple)):
        candidates.extend(reasons[:8])
    found = []
    for value in candidates:
        if isinstance(value, str) and value.strip():
            value = value.strip()[:160]
            if value not in found:
                found.append(value)
        if len(found) == 8:
            break
    return found or [str(result.get('status') or 'independent_outcome_adapter_unavailable')[:160]]


def maturity_report(entries, *, as_of):
    """Read source-index metadata only; no forecast mutation or inferred outcome.

    Native parent counts are descriptive, not certified independent event counts.
    Sports event_end_time in existing records is the scheduled start; a one-hour
    verification delay mirrors the existing official scheduler, not finality.
    """
    now = at(as_of)
    counts = Counter(); reasons = Counter(); groups = set(); due_groups = set(); domains = {}
    identities = {}; conflicts = set()
    for number, entry in enumerate(entries):
        if number >= 10000:
            raise ValueError('bounded_outcome_readiness_inventory_required')
        if not isinstance(entry, dict):
            reasons['invalid_forecast_inventory_row'] += 1
            continue
        f = entry.get('forecast', entry)
        if entry.get('type') not in (None, 'forecast'):
            continue
        try:
            identity = f['id']; checksum = digest(f)
            if not isinstance(identity, str) or not 1 <= len(identity) <= 256:
                raise ValueError('bounded_original_forecast_identity_required')
            if identity in identities and identities[identity][1] != checksum:
                conflicts.add(identity)
            else:
                identities.setdefault(identity, (entry, checksum))
        except (TypeError, KeyError, ValueError):
            reasons['invalid_forecast_inventory_row'] += 1
    for identity in conflicts:
        identities.pop(identity, None)
        reasons['conflicting_original_forecast_identity'] += 1
    for entry, _ in identities.values():
        f = entry.get('forecast', entry)
        try:
            end, created, cutoff = at(f['event_end_time']), at(f['timestamp']), at(f['evidence_cutoff'])
            available = at(entry.get('available_at', f['timestamp']))
            if not cutoff <= created <= available <= now or not available < end:
                raise ValueError('original_prospective_timestamp_binding_required')
            domain = f['domain']; event = f['event_id']
            if not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (domain, event)):
                raise ValueError('bounded_parent_domain_identity_required')
            if entry.get('type') == 'forecast' and entry.get('replay_verified') is not True:
                raise ValueError('original_forecast_source_replay_unverified')
        except (KeyError, TypeError, ValueError):
            reasons['original_prospective_metadata_unqualified'] += 1
            continue
        group = (domain, event); groups.add(group)
        d = domains.setdefault(domain, Counter())
        counts['forecasts'] += 1; d['forecasts'] += 1
        if end <= now:
            counts['nominal_event_boundary_passed'] += 1; d['nominal_event_boundary_passed'] += 1
        else:
            counts['future_event_boundary'] += 1; d['future_event_boundary'] += 1
        if domain == 'sports' and end <= now:
            counts['scheduled_sports_start_passed_not_finality'] += 1
        due = end + (timedelta(hours=1) if domain == 'sports' else timedelta()) <= now
        if due:
            counts['verification_due_forecasts'] += 1; d['verification_due_forecasts'] += 1; due_groups.add(group)
    keys = ('forecasts', 'nominal_event_boundary_passed', 'future_event_boundary',
            'scheduled_sports_start_passed_not_finality', 'verification_due_forecasts')
    return {'schema_version': 'phase29-outcome-readiness-v1', 'as_of': now.isoformat(),
            'counts': {k: counts[k] for k in keys}, 'native_parent_groups': len(groups),
            'verification_due_native_parent_groups': len(due_groups),
            'domains': {k: dict(v) for k, v in sorted(domains.items())}, 'rejections': dict(reasons),
            'independently_verified_outcomes': None, 'certified_independent_events': None,
            'scope': 'current source-replayed forecast inventory; maturity never implies outcome finality or independence', **AUTHORITY}


def native_resolution_diagnostics(payload, *, condition_id):
    """Explain why a public response cannot pass the existing native protocol.

    Even a complete-looking object is NOT verified; chain/rules/source replay
    remains mandatory. Prices, closed flags and proposed prices are never labels.
    """
    if not isinstance(condition_id, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', condition_id):
        raise ValueError('exact_native_condition_identity_required')
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list) or len(payload['data']) > 100:
        return {'status': 'withheld', 'reasons': ['bounded_native_resolution_rows_required'], **AUTHORITY}
    rows = payload['data']
    if len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get('condition_id') != condition_id:
        return {'status': 'withheld', 'reasons': ['single_exact_native_condition_resolution_required'], **AUTHORITY}
    row = rows[0]; missing = [k for k in REQUIRED_FINALITY_FIELDS if k not in row or row[k] is None or row[k] == '']
    reasons = []
    if row.get('new_version_q') is not False:
        reasons.append('unsupported_native_new_version_question_requires_verified_protocol')
    if row.get('status') != 'resolved':
        reasons.append('native_resolution_not_final')
    if row.get('extended_review') is not False or row.get('was_disputed') is not False or row.get('was_arbitrated') is True:
        reasons.append('native_review_dispute_or_finality_unqualified')
    if missing:
        reasons.append('native_finality_fields_missing')
    payouts = row.get('payouts')
    if not isinstance(payouts, list) or payouts not in ([1000000, 0], [0, 1000000]) or not all(type(x) is int for x in payouts):
        reasons.append('verified_binary_payout_vector_unavailable')
    return {'status': 'withheld' if reasons else 'structural_candidate_requires_independent_chain_replay',
            'condition_id': condition_id, 'missing_fields': missing, 'reasons': reasons,
            'canonical_response_sha256': digest(payload), 'verified': False, 'outcome': None,
            'scope': 'schema/protocol attribution only; existing exact identity/rules/native/chain proof gates unchanged', **AUTHORITY}
