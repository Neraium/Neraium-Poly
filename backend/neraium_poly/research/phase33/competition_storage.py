"""Future-only competition storage codec, separate from frozen model source."""
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.research.phase16.checkpoints import CODEC, unpack_checkpoint
from neraium_poly.research.phase33.storage import pack_dense_checkpoint


class CompetitionStoragePolicy(Record):
    policy: dict
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


class CompetitionStorageAdapter:
    """Future checkpoint wire codec only; frozen competition state is unchanged.

    The producer intentionally binds logical state rather than gzip bytes. Reads
    delegate unchanged, including legacy gzip1 checkpoints. New records are
    copied before publication; callers must obtain physical source hashes from
    the immutable store, as with every other stored research source.
    """
    def __init__(self,store,*,clock,can_write):
        import json
        from pathlib import Path

        from neraium_poly.research.phase14.relationships import digest

        self.store=store
        policy={'version':'phase34-competition-lossless-checkpoint-v1',
            'implementation_sha256':digest(Path(__file__).read_text()),
            'codec':CODEC,'gzip_level':6,'legacy_read':'unchanged original wire',
            'scope':'future CompetitionStudy.checkpoint only; same logical state, IDs and source times',
            'retention':'retain all original records; no rewrite or deletion',
            'research_only':True,'trading_authority':False,'certification_authority':False}
        identity=digest(['competition-storage-policy',policy]);value=store.get(identity)
        if value is not None:
            body=value if isinstance(value,dict) else json.loads(value[1])
            row=CompetitionStoragePolicy.model_validate(body)
            if row.id!=identity or row.policy!=policy:raise ValueError('competition storage policy mismatch')
        else:
            if not can_write():raise ValueError('competition storage policy archive unavailable')
            now=clock()
            store.append(CompetitionStoragePolicy(id=identity,timestamp=now,available_at=now,
                source='neraium-poly/competition-storage/v34',policy=policy))
        self.policy_id=identity

    def __getattr__(self,name):return getattr(self.store,name)

    def append(self,record):
        from neraium_poly.research.phase14.relationships import digest
        from neraium_poly.research.phase23.operations import CompetitionStudy

        if type(record) is not CompetitionStudy:return self.store.append(record)
        state=unpack_checkpoint(record.checkpoint)
        if (record.trading_authority is not False or record.certification_authority is not False
            or digest(state)!=record.checkpoint_sha256):
            raise ValueError('competition source checkpoint or authority mismatch')
        existing=self.store.get(record.id)
        if existing is not None:
            import json
            if not isinstance(existing,dict) and existing[0]!='CompetitionStudy':
                raise ValueError('competition archive identity collision')
            body=existing if isinstance(existing,dict) else json.loads(existing[1])
            prior=CompetitionStudy.model_validate(body)
            prior_state=unpack_checkpoint(prior.checkpoint)
            declared=record.model_dump(mode='json')
            if (digest(prior_state)!=prior.checkpoint_sha256 or prior_state!=state
                or {k:v for k,v in body.items() if k!='checkpoint'}
                !={k:v for k,v in declared.items() if k!='checkpoint'}):
                raise ValueError('competition archive identity collision')
            return False  # Keep exact original gzip1/gzip6 bytes on retries.
        packed=pack_dense_checkpoint(state)
        if packed['raw_sha256']!=record.checkpoint['raw_sha256']:
            raise ValueError('competition logical state changed during wire compression')
        physical=record.model_copy(update={'checkpoint':packed})
        return self.store.append(physical)
