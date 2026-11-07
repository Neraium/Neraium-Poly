"""Bounded immediate-YES checks in the existing append-only research archive.

Native finality is mandatory. Reference hits are evidence for a check, never a
settlement. The original P18 model/checkpoint and all forecasts remain unchanged.
"""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path

from pydantic import Field

from neraium_poly.contracts import MarketSnapshot, Record
from neraium_poly.research.phase12.contracts import SettlementProofReference
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome
from neraium_poly.research.phase14.contracts import DomainContract
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.sources import collect_event_evidence
from neraium_poly.research.phase21.outcomes import reference_condition, verify_crypto_outcome


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError('aware early resolution time required')
    return at.astimezone(UTC)


class EventResolutionStudy(Record):
    parent_id: str | None = None
    operation: str = 'reference_check'
    original_study_id: str | None = None
    forecast: dict | None = None
    evidence: list[dict] = Field(default_factory=list)
    outcome: dict | None = None
    model_result: dict = Field(default_factory=dict)
    checks: list[dict] = Field(default_factory=list)
    checkpoint: dict
    checkpoint_sha256: str
    trading_authority: bool = False
    certification_authority: bool = False


class EarlyOutcomeResearch:
    """One asset refresh /300seconds, at most one native proof request per refresh."""
    def __init__(self, store, directory, *, clock=None, can_write=None, collector=None):
        self.store, self.directory = store, Path(directory)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.can_write = can_write or (lambda: True)
        self.collector = collector or collect_event_evidence
        self.code_sha256 = sha256(b''.join(Path(__file__).with_name(n).read_bytes()
            for n in ('continuous.py', 'outcomes.py'))).hexdigest()
        self.last_id = self.pending_commit = self.last_error = None
        self.originals = {}
        self.state = {'code_sha256': self.code_sha256, 'last_at': None, 'last_attempt_at': None,
            'last_symbol': None, 'source_checks': 0, 'conditions_considered': 0,
            'eligible_conditions': 0, 'native_attempts': 0, 'verified': 0, 'verified_ids': {}, 'native_checked_at': {}, 'rejections': {}}
        rows = store.latest('EventResolutionStudy', limit=1)
        if rows:
            row = EventResolutionStudy.model_validate(rows[0])
            if (digest(row.checkpoint) != row.checkpoint_sha256 or row.trading_authority or row.certification_authority
                or row.checkpoint.get('code_sha256') != self.code_sha256
                or row.checkpoint.get('last_at') != row.available_at.isoformat()
                or len(row.checkpoint.get('verified_ids', {})) > 128
                or len(row.checkpoint.get('native_checked_at', {})) > 128):
                raise ValueError('early outcome checkpoint integrity/policy mismatch; no reset')
            self.state, self.last_id = deepcopy(row.checkpoint), row.id

    def _ready(self):
        try:
            if not self.can_write():
                return False
            if hasattr(self.store, 'status'):
                a = self.store.status()
                if any(type(a.get(k)) not in (int, float) or not isfinite(a[k]) or a[k] < 0
                       for k in ('free_bytes', 'global_floor_bytes', 'usage_bytes', 'budget_bytes')):
                    return False
                reserve = 16*1024**2
                return (a.get('health') == 'ok' and a['free_bytes'] >= a['global_floor_bytes']+reserve
                        and a['usage_bytes']+reserve <= a['budget_bytes'])
            return True
        except Exception:  # noqa: BLE001 - unavailable archive capacity denies native/source acquisition
            return False

    def _commit(self, before, **fields):
        now = _at(self.clock())
        self.state['last_at'] = now.isoformat()
        row = EventResolutionStudy(id=digest(['early-outcome-v21', self.last_id, self.state, fields]),
            timestamp=now, available_at=now, source='neraium-poly/early-outcome-research/v21',
            parent_id=self.last_id, checkpoint=deepcopy(self.state), checkpoint_sha256=digest(self.state), **fields)
        self.pending_commit = row
        try:
            self.store.append(row)
        except Exception:
            self.state, self.last_error = before, 'early_outcome_commit_unavailable'
            raise
        self.last_id, self.pending_commit, self.last_error = row.id, None, None
        return True

    async def step(self, pending):
        if self.pending_commit:
            self.store.append(self.pending_commit)
            self.state, self.last_id = deepcopy(self.pending_commit.checkpoint), self.pending_commit.id
            self.pending_commit = None
        now = _at(self.clock())
        if not self._ready():
            self.last_error = 'early_outcome_storage_backpressure'
            return False
        if self.state['last_attempt_at'] and (now-_at(self.state['last_attempt_at'])).total_seconds() < 300:
            return False
        if not isinstance(pending, dict) or len(pending) > 128:
            raise ValueError('bounded pending forecast identities required')
        missing = set(pending)-set(self.originals)-set(self.state['verified_ids'])
        if missing:
            rows = self.store.latest('EventProbabilityStudy', limit=1000)
            for row in rows:
                if row.get('operation') == 'forecast_scan' and (row.get('forecast') or {}).get('id') in pending:
                    self.originals[row['forecast']['id']] = row
        self.originals = {k: v for k, v in self.originals.items() if k in pending}
        groups = {}
        for fid, original in self.originals.items():
            c = DomainContract.model_validate(original['contract'])
            if (fid not in self.state['verified_ids'] and c.contract_type == 'binance_daily_low_barrier'
                and _at(c.parameters['period_start_utc']) <= now < _at(c.parameters['period_end_utc'])):
                groups.setdefault(c.parameters['symbol'], []).append(original)
        if not groups:
            self.last_error = 'no_open_exact_daily_window_or_original_unavailable' if missing-set(self.originals) else None
            return False
        symbols = sorted(groups)
        symbol = next((s for s in symbols if s != self.state['last_symbol']), symbols[0])
        originals = sorted(groups[symbol], key=lambda r: (r['forecast']['timestamp'], r['forecast']['id']))
        before = deepcopy(self.state)
        self.state.update(last_attempt_at=now.isoformat(), last_symbol=symbol)
        self.state['verified_ids'] = {k: v for k, v in self.state['verified_ids'].items() if k in pending}
        self.state['native_checked_at'] = {k: v for k, v in self.state['native_checked_at'].items() if k in pending}
        fields = {'model_result': {'status': 'withheld', 'reasons': []}}
        try:
            evidence = await self.collector(DomainContract.model_validate(originals[0]['contract']), now=now)
            if len(evidence) != 1:
                raise ValueError('one exact reference asset required')
            checked_at = _at(self.clock())
            checks = [reference_condition(o, evidence[0], as_of=checked_at) for o in originals]
            self.state['source_checks'] += 1
            self.state['conditions_considered'] += len(checks)
            self.state['eligible_conditions'] += sum(c['eligible_for_native_check'] for c in checks)
            fields.update(evidence=[e.model_dump(mode='json') for e in evidence], checks=checks,
                model_result={'status': 'reference_checked_not_a_settlement', 'reasons': []})
            eligible = min(((o, c) for o, c in zip(originals, checks, strict=True) if c['eligible_for_native_check']),
                key=lambda pair: (self.state['native_checked_at'].get(pair[0]['forecast']['id'], ''),
                                  pair[0]['forecast']['timestamp'], pair[0]['forecast']['id']), default=None)
            if eligible:
                original, condition = eligible
                f = original['forecast']
                self.state['native_attempts'] += 1
                self.state['native_checked_at'][f['id']] = checked_at.isoformat()
                reference = SettlementProofReference(id=f['id'], event_id=f['event_id'], market_id=f['market_id'],
                    token_id=f['token_id'], timestamp=f['timestamp'], evidence_cutoff=f['evidence_cutoff'],
                    resolution_rules_sha256=f['rules_sha256'], original_record_sha256=digest(f))
                output = self.directory/(checked_at.strftime('%Y%m%dT%H%M%S%fZ')+'-'+f['id'][:12])
                fields.update(operation='outcome_check', forecast=f, original_study_id=original['id'])
                outcome = await acquire_verified_outcome(reference, MarketSnapshot.model_validate(original['market']), output, clock=self.clock)
                if outcome is None:
                    raise ValueError('native_final_settlement_not_available')
                label = {**fields, 'outcome': outcome.model_dump(mode='json'),
                    'timestamp': _at(self.clock()).isoformat(), 'available_at': _at(self.clock()).isoformat(),
                    'model_result': {'status': 'native_and_reference_verified', 'reference_payout': condition['selected_payout']}}
                verified = await asyncio.to_thread(verify_crypto_outcome, label, original,
                    evidence_root=self.directory, as_of=_at(self.clock()))
                if not verified:
                    raise ValueError('native_and_reference_replay_required')
                fields.update(outcome=label['outcome'], model_result=label['model_result'])
                self.state['verified'] += 1
                self.state['verified_ids'][f['id']] = outcome.id
        except Exception as error:  # noqa: BLE001 - no proposed reference condition is a label
            reason = str(error)[:160] or type(error).__name__
            rejections = self.state['rejections']
            key = reason if reason in rejections or len(rejections) < 32 else 'other_bounded_rejection'
            rejections[key] = rejections.get(key, 0)+1
            fields['model_result'] = {'status': 'withheld', 'reasons': [reason]}
            fields['outcome'] = None
        if not self._ready():
            self.state, self.last_error = before, 'early_outcome_storage_backpressure'
            return False
        return self._commit(before, **fields)

    def summary(self):
        return {**deepcopy(self.state), 'status': 'research_only', 'last_error': self.last_error,
            'counter_scope': 'durable source checks and native attempts; conditions are not independent events',
            'trading_authority': False, 'certification_authority': False}
