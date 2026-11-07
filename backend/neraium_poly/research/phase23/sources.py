"""Reuse the byte-hashed native public source; no fallback or availability claims."""
from neraium_poly.research.phase18.sources import collect_event_evidence


async def collect_challenger_evidence(contract, *, now):
    return await collect_event_evidence(contract, now=now)


def load_existing_sports(source_root, *, cutoff):
    """Read-only verified snapshot references; originals remain in their journal.

    At most the latest four immutable source directories are inspected. Manifest
    and raw source hashes are fully checked by the existing adapter. Historical
    game availability remains actual retrieval, never inferred game dates.
    """
    from pathlib import Path

    from neraium_poly.research.phase13.sources import load_sports

    root=Path(source_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('existing_sports_source_snapshot_unavailable')
    for path in sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink()), reverse=True)[:4]:
        data=load_sports(path)
        if all(a.available_at<=cutoff for a in data['artifacts']):
            return data,{'snapshot':str(path),'manifest_sha256':data['manifest_sha256'],
                'artifacts':[a.model_dump(mode='json') for a in data['artifacts']],
                'availability_basis':'actual_original_retrieval','source_lineage':'nflverse:games.csv'}
    raise ValueError('causal_sports_source_snapshot_unavailable')
