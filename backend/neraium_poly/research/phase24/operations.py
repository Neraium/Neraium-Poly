"""Unified research views; conditional forecasts never become token-price claims."""

import json
from collections import Counter
from datetime import UTC, datetime

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase23.operations import competition_report
from neraium_poly.research.phase23.outcomes import verify_outcome as replay_crypto
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.evaluation import evaluate, replay_nfl_outcome


def original(store,identity):
    value=store.get(identity)
    if value is None:raise ValueError('immutable original research record unavailable')
    return value if isinstance(value,dict) else json.loads(value[1])


def domain_studies(store):
    rows=latest(store,'DomainResearchStudy')
    if rows:
        state=unpack_checkpoint(rows[0]['checkpoint'])
        if digest(state)!=rows[0]['checkpoint_sha256']:raise ValueError('domain report checkpoint mismatch')
        eid=state.get('enrollment_record_id')
        if eid and eid not in {r['id'] for r in rows}:rows.append(original(store,eid))
    return rows


def combined_report(store,*,as_of=None,evidence_root):
    now=as_of or datetime.now(UTC)
    from pathlib import Path

    from neraium_poly.research.phase24.outcomes import replay_domain_outcome
    root=Path(evidence_root)
    old=competition_report(store,as_of=now,evidence_root=root.parent/'phase23-resolution-evidence')
    studies=latest(store,'ChallengerStudy')+domain_studies(store)
    outcomes=[r for r in latest(store,'DomainOutcomeStudy') if r.get('result',{}).get('status')=='verified']
    crypto=[r for r in latest(store,'ChallengerOutcomeStudy') if r.get('outcome')]
    def verify(row,f):
        study=original(store,row['original_study_id'])
        if digest(study)!=row.get('original_study_sha256'):raise ValueError('original source hash mismatch')
        if 'result' not in row:proof=replay_crypto(row,study,f,evidence_root=root.parent/'phase23-resolution-evidence',as_of=now)
        elif row['adapter']=='legacy_nfl':proof=replay_nfl_outcome(row,study,f,evidence_root=root/'legacy_nfl',as_of=now)
        else:proof=replay_domain_outcome(row,study,f,evidence_root=root,as_of=now)
        if datetime.fromisoformat(study['available_at'])>=datetime.fromisoformat(proof['resolved_at']):raise ValueError('durable original must precede resolution')
        return proof
    result=evaluate(studies,outcomes+crypto,as_of=now,outcome_verifier=verify)
    domains=Counter();parents=set();conditions=Counter()
    for s in studies:
        for f in s.get('forecasts',[]):
            domains[f['domain']]+=1;parents.add(f['event_id'])
            if f.get('unconditional_contract_probability') is False or f.get('target_conditioning'):conditions[f.get('target_conditioning') or 'explicit_contract_conditions']+=1
    result.update(domains=dict(domains),native_parent_ids=len(parents),conditional_forecasts=dict(conditions),
        phase23_compatible_baseline=old,
        comparison_scope='two prospective model registries; legacy Phase18/13 originals separately reconciled, never lost or pooled as independent events',
        view_scope='latest bounded32MiB per registry plus immutable declaration; not all-time counts',
        conditional_comparison_policy='actual quote is expected payout; never coerce into a conditional win/temperature probability',
        independent_forecast_evidence=True,independent_event_count=0)
    return result
