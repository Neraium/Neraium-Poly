"""Combined authentic source/model review, verification and prospective competition."""
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.evaluation import evaluate, replay_nfl_outcome
from neraium_poly.research.phase24.operations import domain_studies, original
from neraium_poly.research.phase24.outcomes import replay_domain_outcome
from neraium_poly.research.phase24.reconciliation import _replay_archive
from neraium_poly.research.phase25.continuous import ScopedStore, modules


def unified_report(store,*,as_of=None,evidence_root):
    from neraium_poly.research.phase23.outcomes import verify_outcome as crypto
    from neraium_poly.research.phase25.competition import competition_report, executable_diagnostic
    now=as_of or datetime.now(UTC);root=Path(evidence_root);scope=ScopedStore(store)
    studies=latest(store,'ChallengerStudy')+domain_studies(store)+domain_studies(scope)
    scopes={s['id']:('phase25_expansion' if s.get('source','').endswith('/v25') else 'phase24_domains' if s.get('source','').endswith('/v24') else 'phase23_challengers') for s in studies}
    def forecast_proof(study,f,*,as_of):
        _replay_archive(study,f,scopes[study['id']],root.parent,as_of)
        return {'verified':True}
    outcomes=[]
    for kind in ('ExpansionOutcomeStudy','DomainOutcomeStudy','ChallengerOutcomeStudy'):
        outcomes.extend(r for r in latest(store,kind) if r.get('result',{}).get('status')=='verified' or r.get('outcome'))
    def outcome_proof(row,f):
        s=original(store,row['original_study_id'])
        if digest(s)!=row['original_study_sha256']:raise ValueError('immutable outcome source hash mismatch')
        if row.get('source','').endswith('/v25'):
            return replay_domain_outcome(row,s,f,evidence_root=root,as_of=now,modules=modules())
        if row.get('adapter')=='legacy_nfl':return replay_nfl_outcome(row,s,f,evidence_root=root.parent/'phase24-resolution-evidence'/'legacy_nfl',as_of=now)
        if row.get('result') is not None:return replay_domain_outcome(row,s,f,evidence_root=root.parent/'phase24-resolution-evidence',as_of=now)
        return crypto(row,s,f,evidence_root=root.parent/'phase23-resolution-evidence',as_of=now)
    result=evaluate(studies,outcomes,as_of=now,outcome_verifier=outcome_proof)
    result['research_competition']=competition_report(studies,outcomes,as_of=now,forecast_verifier=forecast_proof,outcome_verifier=outcome_proof)
    reviewed={r['forecast_id'] for r in result['research_competition']['event_review']['reviews']}
    result['edge_diagnostics']=[executable_diagnostic(f,evaluated_at=f['timestamp'],forecast_verified=f['id'] in reviewed)
        for s in studies for f in s.get('forecasts',[])]
    result['edge_diagnostic_scope']='replay of admission guards on immutable prospective inputs; not historical trading decisions or fills'
    result['domains']=dict(Counter(f['domain'] for s in studies for f in s.get('forecasts',[])))
    result['view_scope']='bounded32MiB tail per registry plus immutable declarations; legacy Phase18/13 are separately reconciled'
    return result
