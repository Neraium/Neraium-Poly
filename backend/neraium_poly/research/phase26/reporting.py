"""Replay callbacks for the source-anchored incremental research projection."""
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.operations import original
from neraium_poly.research.phase24.reconciliation import _replay_archive


def callbacks(store,source_directory):
    def forecast(study,f,*,as_of):
        scope='phase25_expansion' if study.get('source','').endswith('/v25') else 'phase24_domains' if study.get('source','').endswith('/v24') else 'phase23_challengers'
        _replay_archive(study,f,scope,source_directory,as_of)
        return {'verified':True,'forecast_sha256':digest(f),'original_study_sha256':digest(study)}
    def outcome(row,f,*,as_of=None):
        from datetime import UTC, datetime

        from neraium_poly.research.phase23.outcomes import verify_outcome as crypto
        from neraium_poly.research.phase24.evaluation import replay_nfl_outcome
        from neraium_poly.research.phase24.outcomes import replay_domain_outcome
        from neraium_poly.research.phase25.continuous import modules
        now=as_of or datetime.now(UTC);s=original(store,row['original_study_id'])
        if digest(s)!=row['original_study_sha256']:raise ValueError('projection outcome original hash mismatch')
        full=next(x for x in s['forecasts'] if x['id']==f['id'])
        if row.get('source','').endswith('/v25'):
            return replay_domain_outcome(row,s,full,evidence_root=source_directory/'phase25-resolution-evidence',as_of=now,modules=modules())
        if row.get('adapter')=='legacy_nfl':return replay_nfl_outcome(row,s,full,evidence_root=source_directory/'phase24-resolution-evidence'/'legacy_nfl',as_of=now)
        if row.get('result') is not None:return replay_domain_outcome(row,s,full,evidence_root=source_directory/'phase24-resolution-evidence',as_of=now)
        return crypto(row,s,full,evidence_root=source_directory/'phase23-resolution-evidence',as_of=now)
    return forecast,outcome
